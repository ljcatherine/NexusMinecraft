import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml


SECRET = re.compile(r'(password|secret|token|credential|private.?key)', re.I)


def safe_path(root, name=''):
    root = Path(root).resolve(strict=True)
    path = Path(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or '\0' in name:
        raise ValueError('Invalid relative path')
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Symbolic links are not accessible')
    resolved = current.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('Path escapes server root')
    return current


def protected(path):
    parts = [p.lower() for p in Path(path).parts]
    return any(p.startswith('world') or p.endswith(('.mca', '.mcr', '.dat', '.ldb')) or p == 'skyfactory_world' for p in parts)


def properties(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line and not line.lstrip().startswith(('#', '!')))


def update_properties(text, updates):
    lines = text.splitlines()
    remaining = dict(updates)
    for i, line in enumerate(lines):
        key = line.split('=', 1)[0].strip()
        if not line.lstrip().startswith(('#', '!')) and key in updates:
            lines[i] = key + '=' + str(updates[key])
            remaining.pop(key, None)
    return '\n'.join(lines + [f'{k}={v}' for k, v in remaining.items()]) + '\n'


def validate_text(path, text):
    if len(text.encode()) > 2 * 1024 * 1024 or '\0' in text:
        raise ValueError('Text exceeds size limit or contains binary data')
    suffix = Path(path).suffix.lower()
    if suffix == '.json':
        json.loads(text)
    if suffix in ('.yml', '.yaml'):
        yaml.safe_load(text)
    if Path(path).name == 'server.properties':
        if any(SECRET.search(k) for k in properties(text)):
            raise ValueError('Edit server.properties through Settings; RCON secrets are protected')


def atomic_write(path, data):
    path = Path(path)
    previous = path.stat() if path.exists() else None
    mode = previous.st_mode & 0o777 if previous else 0o640
    fd, temporary = tempfile.mkstemp(prefix='.panel-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == 'posix':
            # A panel edit must remain writable by the existing Java service user.
            # Retain the shared server group even though a non-root writer cannot
            # retain another account's UID on its newly created inode.
            gid = previous.st_gid if previous else path.parent.stat().st_gid
            os.chown(temporary,-1,gid)
            if gid in [os.getegid(),*os.getgroups()] and (gid != os.getegid() or (previous and previous.st_uid != os.geteuid())):
                mode |= 0o060
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_write_stream(path, source, max_bytes):
    """Atomically install a bounded binary stream without buffering it in RAM."""
    path = Path(path)
    previous = path.stat() if path.exists() else None
    mode = previous.st_mode & 0o777 if previous else 0o640
    fd, temporary = tempfile.mkstemp(prefix='.panel-', dir=path.parent)
    try:
        total = 0
        with os.fdopen(fd, 'wb') as handle:
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError('Upload exceeds size limit')
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == 'posix':
            gid = previous.st_gid if previous else path.parent.stat().st_gid
            os.chown(temporary, -1, gid)
            if gid in [os.getegid(), *os.getgroups()] and (gid != os.getegid() or (previous and previous.st_uid != os.geteuid())):
                mode |= 0o060
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
