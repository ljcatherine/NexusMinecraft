#!/usr/bin/python3
"""Interactive, reversible RCON setup. Run only after reviewing installation."""
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0,'/opt/ps5-server-panel')
from panel.storage import properties, update_properties, atomic_write
from panel.rcon import command


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo')
    config = json.loads(Path('/etc/ps5-panel/config.json').read_text())
    print('This will firewall RCON to loopback, stop both Minecraft services, back up server.properties,')
    print('generate separate private credentials, and restart previously running servers.')
    if input('Type CONFIGURE RCON to continue: ') != 'CONFIGURE RCON':
        raise SystemExit('Cancelled')
    if subprocess.run(['systemctl','is-active','--quiet','minecraft-maintenance.service']).returncode == 0:
        raise SystemExit('Maintenance is active; retry later')
    subprocess.run(['systemctl','enable','--now','ps5-rcon-firewall.service'],check=True)
    manual = []
    for sid,srv in config['servers'].items():
        if subprocess.run(['systemctl','is-active','--quiet',srv['unit']]).returncode != 0:
            continue
        props = properties((Path(srv['root'])/'server.properties').read_text())
        try:
            if props.get('enable-rcon') != 'true':
                raise ValueError('RCON disabled')
            command(int(props.get('rcon.port','25575')),props.get('rcon.password',''),'list')
        except Exception:
            manual.append(srv['name'])
    if manual:
        print('No console transport exists yet for: '+', '.join(manual))
        print('An operator must warn players in those servers in-game now:')
        print('/say Server will restart in 10 seconds for panel setup. Please reconnect shortly.')
        if input('After sending the warning, type WARNED immediately: ') != 'WARNED':
            raise SystemExit('Cancelled without restarting Minecraft')
    for sid,srv in config['servers'].items():
        props = properties((Path(srv['root'])/'server.properties').read_text())
        try:
            if props.get('enable-rcon') == 'true':
                command(int(props.get('rcon.port','25575')),props.get('rcon.password',''),'say Server will restart in 10 seconds for panel setup. Please reconnect shortly.')
        except Exception:
            pass
    print('Waiting 10 seconds before stopping services...')
    time.sleep(10)
    originals = {}
    active = []
    stamp = str(time.time_ns())
    snapshot = Path('/var/lib/ps5-panel/rcon-setup')/stamp
    snapshot.mkdir(parents=True,mode=0o700)
    try:
        for sid,srv in config['servers'].items():
            if subprocess.run(['systemctl','is-active','--quiet',srv['unit']]).returncode == 0:
                active.append(srv['unit'])
            subprocess.run(['systemctl','stop',srv['unit']],check=True,timeout=240)
            path = Path(srv['root'])/'server.properties'
            if path.is_symlink():
                raise ValueError('Symlinked server.properties refused')
            originals[path] = path.read_bytes()
            shutil.copy2(path,snapshot/(sid+'.properties'))
            account = path.stat()
            updated = update_properties(path.read_text(),{'enable-rcon':'true','rcon.port':str(srv['rcon_port']),'rcon.password':secrets.token_urlsafe(32),'broadcast-rcon-to-ops':'false'})
            atomic_write(path,updated.encode())
            os.chown(path,account.st_uid,account.st_gid)
            subprocess.run(['setfacl','-m','u:ps5-panel:rw',str(path)],check=True)
        for unit in active:
            subprocess.run(['systemctl','start',unit],check=True,timeout=240)
        print('Configured. Secrets are stored only in server.properties. Originals are in '+str(snapshot))
        print('Check the panel diagnostics after both servers finish starting.')
    except Exception:
        for path,content in originals.items():
            atomic_write(path,content)
        for unit in active:
            subprocess.run(['systemctl','start',unit],timeout=240)
        raise


if __name__=='__main__':
    main()
