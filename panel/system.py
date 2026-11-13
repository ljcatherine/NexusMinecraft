import json
import os
import subprocess
import time
from pathlib import Path

import psutil


def run(args, timeout=12):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:400] or 'System operation failed')
    return result.stdout


def unit_status(unit):
    try:
        raw = run(['systemctl', 'show', unit, '--property=ActiveState,SubState,MainPID,MemoryCurrent,CPUUsageNSec,ActiveEnterTimestamp,ExecMainStatus'])
        values = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        pid = int(values.get('MainPID', '0'))
        values['pid'] = pid
        values['rss'] = psutil.Process(pid).memory_info().rss if pid else None
        values['uptime'] = time.time() - psutil.Process(pid).create_time() if pid else None
        values['cpu_seconds'] = sum(psutil.Process(pid).cpu_times()[:2]) if pid else None
        return values
    except (OSError, RuntimeError, psutil.Error, ValueError) as exc:
        return {'ActiveState': 'unavailable', 'error': str(exc), 'pid': 0}


def journal(unit, lines=150):
    raw = run(['journalctl', '--unit', unit, '--no-pager', '--output=json', f'--lines={lines}'])
    entries = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
            entries.append({'cursor': item.get('__CURSOR'), 'time': int(item.get('__REALTIME_TIMESTAMP', 0)) / 1e6, 'message': item.get('MESSAGE', ''), 'priority': item.get('PRIORITY', '6')})
        except (ValueError, TypeError):
            continue
    return entries


def host_metrics():
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/' if os.name != 'nt' else 'C:\\')
    return {'time': time.time(), 'cpu': psutil.cpu_percent(), 'memory': memory._asdict(), 'swap': psutil.swap_memory()._asdict(), 'disk': disk._asdict(), 'io': psutil.disk_io_counters()._asdict() if psutil.disk_io_counters() else {}, 'network': psutil.net_io_counters()._asdict(), 'uptime': time.time() - psutil.boot_time()}


def service_action(config, unit, action):
    return run(['sudo', '-n', config['helper'], action, unit], timeout=100)


def backup_listing(root):
    root = Path(root)
    if not root.is_dir():
        return []
    result = []
    # No inferred "successful" state: completion markers depend on discovery.
    for path in sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
        if path.is_symlink():
            continue
        stat = path.stat()
        complete = path.is_dir() and (path/'.complete').is_file() and not (path/'.complete').is_symlink()
        size = sum(p.stat().st_size for p in path.iterdir() if p.is_file() and not p.is_symlink()) if path.is_dir() else stat.st_size
        result.append({'name': path.name, 'directory': path.is_dir(), 'size': size, 'modified': stat.st_mtime, 'completion': 'complete' if complete else 'unverified'})
    return result
