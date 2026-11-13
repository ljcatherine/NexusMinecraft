import asyncio
import io
import json
import os
import re
import secrets
import shutil
import tarfile
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import yaml
from starlette.concurrency import run_in_threadpool

from .auth import Auth, RateLimited
from .storage import safe_path, protected, atomic_write, atomic_write_stream, validate_text, properties, update_properties, SECRET
from . import system, rcon, minecraft
from .marketplace import Marketplace, MarketError, detect as detect_software
from .limits import AuthenticationBodyLimit, UploadRequestLimit


class Login(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=1024)


class Command(BaseModel):
    command: str = Field(min_length=1, max_length=1400)


class FileChange(BaseModel):
    path: str = Field(max_length=1024)
    text: str = Field(default='', max_length=2097152)
    destination: str = Field(default='', max_length=1024)
    operation: str = 'write'
    confirmed: bool = False
    revision: str | None = None
    backup: bool = True


class PlayerAction(BaseModel):
    action: str
    player: str = ''
    reason: str = Field(default='', max_length=200)
    confirmed: bool = False


class Settings(BaseModel):
    values: dict[str, str]


class Restore(BaseModel):
    server: str
    path: str = Field(max_length=256)
    confirmation: str


class Invitation(BaseModel):
    username: str = Field(min_length=1,max_length=64)
    role: str = 'admin'


class MarketInstall(BaseModel):
    source: str = Field(max_length=16)
    project: str = Field(max_length=96)
    version_id: str = Field(max_length=96)
    software: str = Field(max_length=16)
    version: str | None = Field(default=None, max_length=12)
    confirmed: bool = False
    allow_unverified: bool = False


class RedeemInvitation(BaseModel):
    token: str = Field(min_length=32,max_length=128)
    password: str = Field(min_length=12,max_length=1024)


def create_app(config=None, market=None):
    if config is None:
        config = json.loads(Path(os.environ.get('PS5_PANEL_CONFIG', 'config.example.json')).read_text())
    if config.get('public_access') and (config.get('bind') != '127.0.0.1' or not config.get('secure_cookie') or not config.get('origin','').startswith('https://')):
        raise ValueError('Public access requires loopback binding, Secure cookies and an HTTPS origin')
    data = Path(config['data'])
    data.mkdir(parents=True, exist_ok=True)
    auth = Auth(data / 'panel.sqlite3')
    market = market or Marketplace()
    cache = {'host': {}, 'servers': {}, 'error': None}
    locks = {key: asyncio.Lock() for key in config['servers']}
    jobs = {}

    async def sample():
        previous = {}
        status_cache = {}
        last_ping = 0
        while True:
            try:
                cache['host'] = await run_in_threadpool(system.host_metrics)
                now = time.monotonic()
                ping_due = now - last_ping >= 15
                for sid, server in config['servers'].items():
                    status = await run_in_threadpool(system.unit_status, server['unit'])
                    cpu = status.get('cpu_seconds')
                    old = previous.get(sid)
                    status['cpu_percent'] = max(0, (cpu-old[0])/(now-old[1])*100) if cpu is not None and old and old[2] == status['pid'] else None
                    if cpu is not None:
                        previous[sid] = (cpu, now, status['pid'])
                    if ping_due:
                        try:
                            status_cache[sid] = await run_in_threadpool(minecraft.status, server['port'])
                        except (OSError,ValueError):
                            status_cache[sid] = {}
                    cache['servers'][sid] = {'id': sid, 'name': server['name'], 'port': server['port'], 'legacy': server['legacy'], 'status': status, 'players': status_cache.get(sid,{}).get('players'), 'version': status_cache.get(sid,{}).get('version'), 'tps': None, 'heap': None}
                if ping_due:
                    last_ping = now
                cache['error'] = None
            except Exception:
                cache['error'] = 'Metrics collection failed; check panel journal'
            await asyncio.sleep(3)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(sample())
        yield
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    app = FastAPI(title='Nexus Minecraft', lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(AuthenticationBodyLimit)
    app.add_middleware(UploadRequestLimit)
    app.state.auth, app.state.config = auth, config

    def user(request, admin=False):
        session = auth.session(request.cookies.get('panel_session', ''))
        if not session:
            raise HTTPException(401, 'Please sign in')
        if admin and session['role'] != 'admin':
            raise HTTPException(403, 'Administrator access required')
        return session

    def server(sid):
        if sid not in config['servers']:
            raise HTTPException(404, 'Unknown server')
        return config['servers'][sid]

    def execute(sid, text):
        srv = server(sid)
        props = properties((Path(srv['root']) / 'server.properties').read_text())
        if props.get('enable-rcon', '').strip() != 'true':
            raise ValueError('RCON is disabled; complete the deployment RCON setup')
        return rcon.command(srv['rcon_port'], props.get('rcon.password', '').strip(), text)

    def mutation(request, action, detail):
        actor = user(request, True)
        auth.audit(actor['name'], action, detail)

    @app.middleware('http')
    async def security(request, call_next):
        if config.get('public_access'):
            from urllib.parse import urlsplit
            if request.headers.get('host') != urlsplit(config['origin']).netloc:
                return JSONResponse({'detail':'Host rejected'},400)
            if request.url.scheme != 'https':
                return JSONResponse({'detail':'HTTPS required'},426)
        if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('origin') != config['origin']:
                return JSONResponse({'detail': 'Origin rejected'}, 403)
            if request.url.path not in ('/api/login','/api/invites/redeem'):
                session = auth.session(request.cookies.get('panel_session', ''))
                if not session or not secrets.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
                    return JSONResponse({'detail': 'Session or CSRF token rejected'}, 403)
                with auth.db() as db:
                    count = db.execute('SELECT count(*) FROM audit WHERE actor=? AND time>?', (session['name'],time.time()-60)).fetchone()[0]
                if count >= 120:
                    return JSONResponse({'detail':'Action rate limit reached; retry in one minute'},429)
        response = await call_next(request)
        response.headers.update({'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({'detail': str(exc)}, 400)

    @app.exception_handler(RateLimited)
    async def rate_limited(request, exc):
        return JSONResponse({'detail':str(exc)},429,headers={'Retry-After':'900'})

    @app.exception_handler(yaml.YAMLError)
    async def yaml_error(request, exc):
        return JSONResponse({'detail':'Invalid YAML; no changes were saved'},400)

    @app.exception_handler(tarfile.TarError)
    async def archive_error(request, exc):
        return JSONResponse({'detail':'Archive is damaged or unsupported'},400)

    @app.exception_handler(zipfile.BadZipFile)
    async def jar_error(request, exc):
        return JSONResponse({'detail':'Invalid JAR/ZIP file'},400)

    @app.exception_handler(OSError)
    async def os_error(request, exc):
        return JSONResponse({'detail': 'Host operation unavailable; check permissions and configuration'}, 503)

    @app.exception_handler(RuntimeError)
    async def runtime_error(request, exc):
        return JSONResponse({'detail': str(exc)}, 503)

    @app.post('/api/login')
    def login(body: Login, request: Request):
        result = auth.login(body.username, body.password, request.client.host)
        if not result:
            raise HTTPException(401, 'Invalid username or password')
        token, csrf = result
        auth.audit(body.username, 'login', '')
        response = JSONResponse({'csrf': csrf})
        response.set_cookie('panel_session', token, httponly=True, secure=config.get('secure_cookie', True), samesite='strict', max_age=28800)
        return response

    @app.get('/api/me')
    def me(request: Request):
        return user(request)

    @app.get('/api/accounts')
    def accounts(request: Request):
        user(request,True)
        return auth.accounts()

    @app.post('/api/invites')
    def invite(body: Invitation, request: Request):
        actor = user(request,True)
        token = auth.invite(body.username,body.role,actor['name'])
        return {'username':body.username,'role':body.role,'url':config['origin']+'/#invite='+token,'expires_in':86400}

    @app.post('/api/invites/redeem')
    def redeem(body: RedeemInvitation, request: Request):
        name = auth.redeem(body.token,body.password,request.client.host)
        return {'username':name}

    @app.post('/api/logout')
    def logout(request: Request):
        with auth.db() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (auth.digest(request.cookies.get('panel_session', '')),))
        response = JSONResponse({'ok': True})
        response.delete_cookie('panel_session')
        return response

    @app.get('/api/dashboard')
    def dashboard(request: Request):
        user(request)
        return cache

    @app.post('/api/servers/{sid}/power/{action}')
    async def control(sid: str, action: str, request: Request):
        srv = server(sid)
        if action not in ('start', 'stop', 'restart'):
            raise HTTPException(404)
        mutation(request, 'service.'+action, sid)
        async with locks[sid]:
            await run_in_threadpool(system.service_action, config, srv['unit'], action)
        return {'ok': True}

    @app.get('/api/servers/{sid}/logs')
    def logs(sid: str, request: Request):
        user(request)
        return system.journal(server(sid)['unit'], 400)

    @app.post('/api/servers/{sid}/command')
    def console(sid: str, body: Command, request: Request):
        mutation(request, 'rcon.command', sid)  # Commands may contain secrets; do not persist text.
        return {'result': execute(sid, body.command)}

    @app.get('/api/servers/{sid}/players')
    def players(sid: str, request: Request):
        user(request)
        root = Path(server(sid)['root'])
        result = {'online': None, 'error': None, 'ping': None, 'recent': [], 'capabilities': {'ping': False, 'uuid_online': False}}
        try:
            result['online'] = execute(sid, 'list')
        except (OSError, ValueError, ConnectionError) as exc:
            result['error'] = str(exc)
        for key, filename in [('ops', 'ops.json'), ('whitelist', 'whitelist.json'), ('banned', 'banned-players.json'), ('known', 'usercache.json')]:
            path = safe_path(root, filename)
            result[key] = json.loads(path.read_text()) if path.is_file() else []
        try:
            result['recent'] = [row for row in system.journal(server(sid)['unit'], 300) if re.search(r'joined the game|left the game', str(row['message']))][-30:]
        except (OSError, RuntimeError):
            pass
        return result

    @app.post('/api/servers/{sid}/players')
    def player_action(sid: str, body: PlayerAction, request: Request):
        allowed = {'kick':'kick', 'ban':'ban', 'unban':'pardon', 'op':'op', 'deop':'deop', 'whitelist-add':'whitelist add', 'whitelist-remove':'whitelist remove', 'whitelist-on':'whitelist on', 'whitelist-off':'whitelist off', 'broadcast':'say'}
        if body.action not in allowed or not body.confirmed:
            raise ValueError('Valid action and explicit confirmation required')
        text = allowed[body.action]
        if body.action not in ('whitelist-on', 'whitelist-off', 'broadcast'):
            if not re.fullmatch(r'[A-Za-z0-9_]{1,16}', body.player):
                raise ValueError('Invalid Minecraft username')
            text += ' '+body.player
        if body.action in ('kick', 'ban', 'broadcast'):
            text += ' '+body.reason
        mutation(request, 'player.'+body.action, sid+':'+body.player)
        return {'result': execute(sid, text)}

    def check_file(sid, name, writing=False):
        srv = server(sid)
        path = safe_path(srv['root'], name)
        if any(SECRET.search(p) or p.startswith('.panel-') for p in Path(name).parts):
            raise ValueError('Sensitive files are not accessible')
        if path.name == 'server.properties':
            raise ValueError('Use Settings to access server.properties without exposing RCON credentials')
        relative_parts = Path(name).parts
        declared_world = srv['world']
        try:
            declared_world = properties(safe_path(srv['root'],'server.properties').read_text()).get('level-name',declared_world)
        except OSError:
            pass
        world_path = Path(declared_world).parts
        in_world = relative_parts[:len(world_path)] == world_path if world_path else False
        if writing and (protected(name) or in_world):
            # Reject all world edits; configuration operations must not mutate live databases.
            raise ValueError('World data cannot be changed through the file manager')
        return path

    @app.get('/api/servers/{sid}/files')
    def files(sid: str, request: Request, path: str = '', search: str = ''):
        user(request)
        folder = safe_path(server(sid)['root'], path)
        result = []
        for child in folder.iterdir():
            if child.is_symlink() or child.name.startswith('.panel-') or SECRET.search(child.name):
                continue
            if search.lower() not in child.name.lower():
                continue
            stat = child.stat()
            result.append({'name': child.name, 'directory': child.is_dir(), 'size': stat.st_size, 'modified': stat.st_mtime, 'editable': child.suffix.lower() in ('.json','.yaml','.yml','.properties','.cfg','.conf','.txt','.log') and child.name != 'server.properties', 'revision': str(stat.st_mtime_ns)})
            if len(result) >= 2000:
                break
        return sorted(result, key=lambda item: (not item['directory'], item['name'].lower()))

    @app.get('/api/servers/{sid}/file')
    def read_file(sid: str, request: Request, path: str):
        # Server configuration and plugin/mod files can hold API keys and other
        # credentials that are unrelated to Minecraft's RCON settings.
        user(request, True)
        target = check_file(sid, path)
        if target.stat().st_size > 2*1024*1024:
            raise ValueError('File too large for editor; download instead')
        return {'text': target.read_text(encoding='utf-8'), 'revision': str(target.stat().st_mtime_ns)}

    @app.get('/api/servers/{sid}/download')
    def download(sid: str, request: Request, path: str):
        user(request, True)
        target = check_file(sid, path)
        if protected(path):
            raise ValueError('Use stopped-server backups for world downloads')
        return FileResponse(target, filename=target.name, media_type='application/octet-stream')

    @app.post('/api/servers/{sid}/files')
    async def change_file(sid: str, body: FileChange, request: Request):
        mutation(request, 'file.'+body.operation, sid+':'+body.path)
        async with locks[sid]:
            target = check_file(sid, body.path, True)
            if target == Path(server(sid)['root']).resolve():
                raise ValueError('Cannot mutate server root')
            if target.exists() and body.revision != str(target.stat().st_mtime_ns):
                raise HTTPException(409, 'File changed; refresh before editing')
            if body.operation == 'write':
                if target.suffix.lower() not in ('.txt','.log','.json','.yaml','.yml','.properties','.cfg','.conf'):
                    raise ValueError('Unsupported text file extension')
                validate_text(target, body.text)
                if target.exists() and body.backup:
                    snapshot = data / 'edits' / sid / str(time.time_ns())
                    snapshot.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, snapshot)
                atomic_write(target, body.text.encode())
            elif body.operation == 'mkdir':
                target.mkdir()
            elif body.operation == 'move':
                destination = check_file(sid, body.destination, True)
                if not body.confirmed or destination.exists():
                    raise ValueError('Confirmation required; destination must not exist')
                if target.is_dir() and any(target.iterdir()):
                    raise ValueError('Only empty directories can be moved through the panel')
                target.rename(destination)
            elif body.operation == 'delete':
                if not body.confirmed:
                    raise ValueError('Deletion requires confirmation')
                # Empty directories only; no recursive deletion of a world through its parent.
                target.rmdir() if target.is_dir() else target.unlink()
            else:
                raise ValueError('Unknown file operation')
        return {'ok': True}

    @app.post('/api/servers/{sid}/upload')
    async def upload(sid: str, request: Request, path: str, file: UploadFile = File(...)):
        mutation(request, 'file.upload', sid+':'+path)
        async with locks[sid]:
            target = check_file(sid, path, True)
            if target.exists():
                raise ValueError('Uploads cannot replace existing files; rename the existing file first')
            if target.suffix.lower() not in ('.json','.yml','.yaml','.cfg','.conf','.txt','.properties'):
                raise ValueError('Unsupported upload type')
            chunks, total = [], 0
            while chunk := await file.read(1024*1024):
                total += len(chunk)
                if total > 64*1024*1024:
                    raise ValueError('Upload limit is 64 MiB')
                chunks.append(chunk)
            content = b''.join(chunks)
            if target.suffix.lower() == '.jar':
                import io
                with zipfile.ZipFile(io.BytesIO(content)) as jar:
                    if len(jar.infolist()) > 50000:
                        raise ValueError('JAR contains too many entries')
            else:
                validate_text(target, content.decode('utf-8'))
            atomic_write(target, content)
        return {'ok': True, 'restart_required': True}

    @app.get('/api/servers/{sid}/settings')
    def settings(sid: str, request: Request):
        user(request)
        srv = server(sid)
        props = properties(safe_path(srv['root'], 'server.properties').read_text())
        allowed = setting_rules(srv)
        return {'values': {k: v for k,v in props.items() if k in allowed}, 'restart_required': True, 'unsupported': ['simulation-distance'] if srv['legacy'] else [], 'startup': {'java': srv['java'], 'jar': srv['jar'], 'editable': False}}

    def setting_rules(srv):
        rules = {'motd': 'text', 'server-port': (1024,65535), 'max-players': (1,100), 'white-list':'bool', 'online-mode':'bool', 'difficulty':'difficulty', 'gamemode':'gamemode', 'view-distance': (2,32), 'pvp':'bool', 'spawn-protection': (0,10000), 'enable-command-block':'bool'}
        if not srv['legacy']:
            rules['simulation-distance'] = (2,32)
        return rules

    @app.put('/api/servers/{sid}/settings')
    async def set_settings(sid: str, body: Settings, request: Request):
        srv = server(sid)
        mutation(request, 'settings.update', sid)
        for key, value in body.values.items():
            rule = setting_rules(srv).get(key)
            if rule is None or any(c in value for c in '\r\n\0') or len(value) > 256:
                raise ValueError('Unsupported setting or invalid value')
            if isinstance(rule, tuple) and not rule[0] <= int(value) <= rule[1]:
                raise ValueError(f'{key} is out of range')
            if rule == 'bool' and value not in ('true','false'):
                raise ValueError('Boolean settings require true or false')
            if rule == 'difficulty' and value not in ('0','1','2','3','peaceful','easy','normal','hard'):
                raise ValueError('Invalid difficulty')
            if rule == 'gamemode' and value not in ('0','1','2','3','survival','creative','adventure','spectator'):
                raise ValueError('Invalid gamemode')
            if srv['legacy'] and key in ('difficulty','gamemode') and not value.isdigit():
                raise ValueError('Minecraft 1.12.2 requires numeric difficulty and gamemode')
            if key == 'server-port' and any(int(value) == other['port'] for other_id, other in config['servers'].items() if other_id != sid):
                raise ValueError('Port conflicts with the other Minecraft server')
        async with locks[sid]:
            target = safe_path(srv['root'], 'server.properties')
            snapshot = data / 'edits' / sid / str(time.time_ns())
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, snapshot)
            atomic_write(target, update_properties(target.read_text(), body.values).encode())
        return {'ok': True, 'restart_required': True}

    @app.get('/api/servers/{sid}/extensions')
    def extensions(sid: str, request: Request):
        user(request)
        srv = server(sid)
        folder = safe_path(srv['root'], 'mods' if srv['legacy'] else 'plugins')
        result = []
        if not folder.exists():
            return result
        for path in folder.iterdir():
            if path.is_symlink() or not path.is_file() or path.suffix not in ('.jar','.disabled'):
                continue
            metadata = None
            try:
                with zipfile.ZipFile(path) as jar:
                    for name in ('plugin.yml', 'paper-plugin.yml', 'mcmod.info', 'META-INF/mods.toml'):
                        if name in jar.namelist() and jar.getinfo(name).file_size < 128000:
                            metadata = jar.read(name).decode('utf-8', errors='replace')
                            break
            except (OSError, zipfile.BadZipFile):
                metadata = 'Unreadable JAR'
            result.append({'name': path.name, 'enabled': path.suffix == '.jar', 'metadata': metadata, 'size': path.stat().st_size})
        return result

    @app.post('/api/servers/{sid}/extensions')
    async def install_extension(sid: str, request: Request, confirmed: bool = Form(False), file: UploadFile = File(...)):
        actor = user(request, True)
        srv = server(sid)
        folder_name = 'mods' if srv['legacy'] else 'plugins'
        filename = file.filename or ''
        if not confirmed:
            raise ValueError('Confirm that you trust this JAR and its source before installing')
        if (Path(filename).name != filename or '/' in filename or '\\' in filename
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,123}\.jar', filename, re.I)):
            raise ValueError('Choose a JAR file with a simple filename')
        size = await install_jar(sid, srv, folder_name, filename, file.file)
        auth.audit(actor['name'], 'extension.install', sid+':'+folder_name+'/'+filename)
        return {'ok': True, 'name': filename, 'directory': folder_name, 'size': size, 'restart_required': True}

    async def install_jar(sid, srv, folder_name, filename, stream):
        """Write a JAR into plugins/ or mods/ atomically; shared by uploads and the marketplace."""
        async with locks[sid]:
            root = safe_path(srv['root'])
            folder = safe_path(root, folder_name)
            folder.mkdir(mode=0o750, exist_ok=True)
            folder = safe_path(root, folder_name)
            if not folder.is_dir():
                raise ValueError('Extension directory is unavailable')
            if any(path.name.casefold() == filename.casefold() for path in folder.iterdir()):
                raise HTTPException(409, 'An extension with that filename already exists; remove or rename it first')
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(0)
            if size == 0 or size > 64 * 1024 * 1024:
                raise ValueError('JAR must be non-empty and no larger than 64 MiB')
            with zipfile.ZipFile(stream) as jar:
                if not jar.infolist() or len(jar.infolist()) > 50000:
                    raise ValueError('JAR must contain 1–50,000 entries')
            stream.seek(0)
            atomic_write_stream(folder / filename, stream, 64 * 1024 * 1024)
        return size

    @app.get('/api/servers/{sid}/marketplace/context')
    def market_context(sid: str, request: Request):
        user(request)
        srv = server(sid)
        return {**detect_software(srv), 'directory': 'mods' if srv['legacy'] else 'plugins'}

    @app.get('/api/servers/{sid}/marketplace/search')
    def market_search(sid: str, request: Request, source: str, software: str, q: str = '', version: str = '', offset: int = 0):
        user(request)
        server(sid)
        return market.search(source, q, software, version or None, offset)

    @app.get('/api/servers/{sid}/marketplace/versions')
    def market_versions(sid: str, request: Request, source: str, project: str, software: str, version: str = ''):
        user(request)
        server(sid)
        return [{k: v for k, v in item.items() if k not in ('url', 'hash')} | {'hash_algorithm': item['hash'][0] if item['hash'] else None}
                for item in market.versions(source, project, software, version or None)]

    @app.post('/api/servers/{sid}/marketplace/install')
    async def market_install(sid: str, body: MarketInstall, request: Request):
        actor = user(request, True)
        srv = server(sid)
        if not body.confirmed:
            raise ValueError('Confirm that you trust this plugin and its source before installing')
        folder_name = 'mods' if srv['legacy'] else 'plugins'
        filename, content, record = await run_in_threadpool(market.fetch, body.source, body.project, body.version_id,
                                                            body.software, body.version, body.allow_unverified)
        size = await install_jar(sid, srv, folder_name, filename, io.BytesIO(content))
        auth.audit(actor['name'], 'extension.install', f"{sid}:{folder_name}/{filename} from {record['source']}:{record['project']}@{record['version']} sha256={record['sha256']}{'' if record['verified'] else ' unverified'}")
        return {'ok': True, 'name': filename, 'directory': folder_name, 'size': size, 'restart_required': True, **record}

    @app.get('/api/marketplace/icon')
    def market_icon(request: Request, url: str):
        user(request)
        body, kind = market.icon(url)
        return Response(body, media_type=kind, headers={'Cache-Control': 'private, max-age=86400'})

    @app.get('/api/backups')
    def backups(request: Request, path: str = ''):
        user(request)
        root = safe_path(config['backups'], path)
        items = system.backup_listing(root)
        result = {'items': items, 'status': system.unit_status('minecraft-maintenance.service'), 'next': None, 'completion': 'Completed sets use the existing .complete marker', 'retained_sets':sum(item['completion']=='complete' for item in items), 'storage':sum(item['size'] or 0 for item in items), 'last_success':next((item['modified'] for item in items if item['completion']=='complete'),None), 'retention_editable': False}
        try:
            result['next'] = system.run(['systemctl','show','minecraft-maintenance.timer','--property=NextElapseUSecRealtime','--value']).strip()
        except (OSError,RuntimeError):
            pass
        return result

    @app.post('/api/backups/run')
    def backup_run(request: Request):
        mutation(request, 'maintenance.start', '')
        system.service_action(config, 'minecraft-maintenance.service', 'start')
        return {'ok': True}

    @app.get('/api/backups/logs')
    def backup_logs(request: Request):
        user(request)
        return system.journal('minecraft-maintenance.service', 300)

    @app.post('/api/backups/restore')
    async def restore(body: Restore, request: Request):
        server(body.server)
        mutation(request, 'restore.requested', body.server+':'+body.path)
        if body.confirmation != 'RESTORE '+body.server:
            raise ValueError('Type RESTORE '+body.server+' to confirm')
        if not config.get('restore_enabled',False):
            raise HTTPException(409,'Restore is locked until the helper passes isolated Debian restore tests and maintenance lock review')
        if any(job['status']=='running' for job in jobs.values()):
            raise HTTPException(409,'A restore is already running')
        safe_path(config['backups'],body.path)
        jobid = secrets.token_hex(12)
        jobs[jobid] = {'id':jobid,'status':'running','server':body.server,'started':time.time(),'result':None}
        async def perform():
            async with locks[body.server]:
                try:
                    result = await run_in_threadpool(system.run,['sudo','-n',config['helper'],'restore',body.server,body.path],3600)
                    jobs[jobid].update(status='succeeded',result=result)
                except Exception as exc:
                    jobs[jobid].update(status='failed',result=str(exc))
                atomic_write(data/('restore-'+jobid+'.json'),json.dumps(jobs[jobid]).encode())
                auth.audit('system','restore.'+jobs[jobid]['status'],body.server+':'+jobid)
        # Keep a strong reference for shutdown/restart recovery reporting.
        jobs[jobid]['task'] = None
        task = asyncio.create_task(perform())
        app.state.restore_task = task
        jobs[jobid].pop('task')
        return {'job':jobid}

    @app.get('/api/backups/jobs/{jobid}')
    def restore_job(jobid: str, request: Request):
        user(request,True)
        if not re.fullmatch('[a-f0-9]{24}',jobid):
            raise HTTPException(404)
        if jobid in jobs:
            return jobs[jobid]
        path = data/('restore-'+jobid+'.json')
        if path.is_file():
            return json.loads(path.read_text())
        raise HTTPException(404,'Unknown job; if panel restarted, inspect the server and rollback directories before retrying')

    @app.get('/api/backups/download')
    def backup_download(request: Request, path: str):
        user(request, True)
        target = safe_path(config['backups'], path)
        return FileResponse(target, filename=target.name, media_type='application/octet-stream')

    @app.get('/api/backups/inspect')
    def backup_inspect(request: Request, path: str):
        user(request)
        target = safe_path(config['backups'], path)
        contents, total, count = [], 0, 0
        with tarfile.open(target, 'r|*') as archive:
            for member in archive:
                if member.name.startswith(('/', '\\')) or '..' in Path(member.name).parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                    raise ValueError('Unsafe archive member found')
                total += member.size
                count += 1
                if count >= 1000000 or total > 500*1024**3:
                    raise ValueError('Archive exceeds inspection limit')
                if len(contents) < 5000:
                    contents.append({'name': member.name, 'size': member.size})
                if member.isfile():
                    stream = archive.extractfile(member)
                    while stream.read(1024*1024):
                        pass
        return {'valid': True, 'expanded_size': total, 'contents': contents, 'total_members':count, 'truncated':count>len(contents)}

    @app.get('/api/diagnostics/{sid}')
    def diagnostics(sid: str, request: Request):
        user(request)
        srv = server(sid)
        root = Path(srv['root'])
        checks = {'service': system.unit_status(srv['unit']), 'java_exists': Path(srv['java']).is_file(), 'jar_exists': (root/srv['jar']).is_file(), 'world_exists': (root/srv['world']).is_dir(), 'root_readable': os.access(root, os.R_OK), 'root_writable': os.access(root, os.W_OK), 'rcon': None}
        try:
            checks['rcon'] = {'ok': True, 'response': execute(sid, 'list')}
        except Exception:
            checks['rcon'] = {'ok': False, 'message': 'Check enable-rcon, per-server port/password, service state, and loopback firewall rules'}
        return checks

    @app.get('/api/audit')
    def audit(request: Request):
        user(request, True)
        with auth.db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 250')]

    @app.websocket('/api/live')
    async def live(ws: WebSocket):
        if ws.headers.get('origin') != config['origin'] or not auth.session(ws.cookies.get('panel_session', '')):
            await ws.close(code=1008)
            return
        await ws.accept()
        try:
            while True:
                if not await run_in_threadpool(auth.session, ws.cookies.get('panel_session', '')):
                    await ws.close(code=1008)
                    return
                await ws.send_json(cache)
                await asyncio.sleep(3)
        except WebSocketDisconnect:
            pass

    @app.websocket('/api/servers/{sid}/console')
    async def live_console(ws: WebSocket, sid: str):
        srv = server(sid)
        if ws.headers.get('origin') != config['origin'] or not auth.session(ws.cookies.get('panel_session', '')):
            await ws.close(code=1008)
            return
        await ws.accept()
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec('journalctl','-u',srv['unit'],'-f','-n','150','-o','json','--no-pager',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            while True:
                if not await run_in_threadpool(auth.session, ws.cookies.get('panel_session', '')):
                    await ws.close(code=1008)
                    break
                try:
                    line = await asyncio.wait_for(proc.stdout.readline(), timeout=10)
                except asyncio.TimeoutError:
                    await ws.send_json({'heartbeat': True})
                    continue
                if not line:
                    await ws.send_json({'error': 'Journal stream ended'})
                    break
                row = json.loads(line)
                await ws.send_json({'time': int(row.get('__REALTIME_TIMESTAMP',0))/1e6, 'message': row.get('MESSAGE',''), 'priority': row.get('PRIORITY','6')})
        except (WebSocketDisconnect, OSError):
            pass
        finally:
            if proc and proc.returncode is None:
                proc.terminate()
                await proc.wait()

    static = Path(__file__).resolve().parent.parent / 'frontend' / 'dist'
    if static.exists():
        app.mount('/', StaticFiles(directory=static, html=True), name='frontend')
    return app
