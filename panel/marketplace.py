"""Plugin and mod marketplace: search Modrinth, Hangar and SpigotMC (Spiget), then install
verified files. Only allowlisted HTTPS hosts are ever contacted, redirects are re-checked hop
by hop, and the browser never supplies a download URL: installs are resolved server-side from
(source, project, version id)."""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import time
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

USER_AGENT = 'ljcatherine/NexusMinecraft/1.0 (+https://github.com/ljcatherine/NexusMinecraft)'
API_HOSTS = {'api.modrinth.com', 'hangar.papermc.io', 'api.spiget.org'}
FILE_HOSTS = {'cdn.modrinth.com', 'hangarcdn.papermc.io', 'cdn.spiget.org'}
ICON_HOSTS = {'cdn.modrinth.com', 'hangarcdn.papermc.io'}
MAX_JSON = 4 * 1024 * 1024
MAX_JAR = 64 * 1024 * 1024
MAX_ICON = 256 * 1024
SOURCES = ('modrinth', 'hangar', 'spiget')

# Which plugin loaders each server software can run (first entry is the native one).
PLUGIN_LOADERS = {
    'paper': ['paper', 'spigot', 'bukkit'],
    'purpur': ['purpur', 'paper', 'spigot', 'bukkit'],
    'folia': ['folia'],
    'spigot': ['spigot', 'bukkit'],
    'bukkit': ['bukkit'],
}
MOD_LOADERS = {'forge': ['forge'], 'neoforge': ['neoforge'], 'fabric': ['fabric'], 'quilt': ['quilt', 'fabric']}
SOFTWARE = tuple(PLUGIN_LOADERS) + tuple(MOD_LOADERS)
VERSION_RE = re.compile(r'^\d{1,2}\.\d{1,2}(\.\d{1,2})?$')
ID_RE = re.compile(r'^[A-Za-z0-9_.+-]{1,96}$')


class MarketError(ValueError):
    """User-facing marketplace failure (rendered as a 400 by the app)."""


def kind_of(software: str) -> str:
    return 'mod' if software in MOD_LOADERS else 'plugin'


def loaders_for(software: str) -> list[str]:
    return PLUGIN_LOADERS.get(software) or MOD_LOADERS.get(software) or []


def _check_url(url: str, hosts: set[str]) -> str:
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in hosts or parts.username or parts.password or parts.port not in (None, 443):
        raise MarketError('Refused to contact a host outside the plugin sources')
    return url


class Http:
    """Tiny allowlisted HTTPS client. Tests replace `transport` with httpx.MockTransport."""

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(transport=transport, timeout=httpx.Timeout(12.0, connect=6.0),
                                   follow_redirects=False, headers={'User-Agent': USER_AGENT})

    def _get(self, url: str, hosts: set[str], limit: int, accept: str):
        for _ in range(4):
            _check_url(url, hosts)
            with self.client.stream('GET', url, headers={'Accept': accept}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('location', '')
                    url = str(httpx.URL(url).join(location))
                    continue
                if response.status_code == 404:
                    raise MarketError('Not found at the plugin source')
                if response.status_code == 429:
                    raise MarketError('The plugin source is rate limiting requests; try again shortly')
                if response.status_code >= 400:
                    raise MarketError(f'The plugin source returned HTTP {response.status_code}')
                declared = response.headers.get('content-length')
                if declared and declared.isdigit() and int(declared) > limit:
                    raise MarketError('The file is larger than the allowed limit')
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise MarketError('The file is larger than the allowed limit')
                return bytes(body), response.headers.get('content-type', ''), url
        raise MarketError('Too many redirects from the plugin source')

    def json(self, url: str):
        body, _, _ = self._get(url, API_HOSTS, MAX_JSON, 'application/json')
        try:
            return json.loads(body)
        except ValueError as exc:
            raise MarketError('The plugin source returned an unreadable response') from exc

    def file(self, url: str) -> bytes:
        body, _, _ = self._get(url, API_HOSTS | FILE_HOSTS, MAX_JAR, 'application/java-archive, application/octet-stream, */*')
        return body

    def icon(self, url: str) -> tuple[bytes, str]:
        body, kind, _ = self._get(url, ICON_HOSTS, MAX_ICON, 'image/*')
        kind = kind.split(';')[0].strip().lower()
        if kind not in ('image/png', 'image/jpeg', 'image/webp', 'image/gif'):
            raise MarketError('Not an image')
        return body, kind


def detect(srv: dict) -> dict:
    """Best guess at the server software and Minecraft version; config keys override it."""
    root = Path(srv.get('root', ''))
    software = srv.get('software')
    version = srv.get('minecraft_version')
    source = 'configuration' if software and version else None
    if not (software and version):
        try:
            history = json.loads((root / 'version_history.json').read_text()[:4096])
            current = history.get('currentVersion', '')
            match = re.search(r'git-(\w+)-.*\(MC: ([0-9.]+)\)', current)
            if match:
                software = software or match.group(1).lower()
                version = version or match.group(2)
                source = source or 'version_history.json'
        except (OSError, ValueError, AttributeError):
            pass
    if not (software and version):
        jar = str(srv.get('jar', '')).lower()
        match = re.search(r'(paper|purpur|folia|spigot|craftbukkit|bukkit|forge|neoforge|fabric)[-_]?(?:server[-_]?)?(?:mc[-_]?)?(\d+\.\d+(?:\.\d+)?)', jar)
        if match:
            software = software or ('bukkit' if match.group(1) == 'craftbukkit' else match.group(1))
            version = version or match.group(2)
            source = source or 'server JAR name'
    if not software:
        software = 'forge' if srv.get('legacy') else 'paper'
        source = source or 'default'
    if software not in SOFTWARE:
        software = 'forge' if srv.get('legacy') else 'paper'
    if version and not VERSION_RE.match(version):
        version = None
    return {'software': software, 'version': version, 'kind': kind_of(software), 'detected_from': source or 'default',
            'sources': [s for s in SOURCES if source_supports(s, software)]}


def source_supports(source: str, software: str) -> bool:
    if source == 'modrinth':
        return True
    if source == 'hangar':
        return software in ('paper', 'purpur', 'folia')
    if source == 'spiget':
        return software in ('paper', 'purpur', 'spigot', 'bukkit')
    return False


def _validate(source: str, software: str, version: str | None):
    if source not in SOURCES:
        raise MarketError('Unknown plugin source')
    if software not in SOFTWARE:
        raise MarketError('Unknown server software')
    if version is not None and version != '' and not VERSION_RE.match(version):
        raise MarketError('Minecraft version must look like 1.21 or 1.21.4')
    if not source_supports(source, software):
        raise MarketError(f'{source.capitalize()} does not offer {kind_of(software)}s for {software}')


def _minor(version: str) -> str:
    return '.'.join(version.split('.')[:2])


class Marketplace:
    def __init__(self, http: Http | None = None):
        self.http = http or Http()
        self._cache: dict[str, tuple[float, object]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: str, ttl: float, produce):
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = produce()
        with self._lock:
            if len(self._cache) > 512:
                self._cache.clear()
            self._cache[key] = (now, value)
        return value

    # ---- search -------------------------------------------------------------------------
    def search(self, source: str, query: str, software: str, version: str | None, offset: int = 0) -> dict:
        _validate(source, software, version)
        query = (query or '').strip()[:80]
        offset = max(0, min(int(offset), 500))
        key = json.dumps([source, query.lower(), software, version, offset])
        return self._cached(key, 120, lambda: getattr(self, f'_search_{source}')(query, software, version, offset))

    def _search_modrinth(self, query, software, version, offset):
        facets = [[f'project_type:{kind_of(software)}'], [f'categories:{loader}' for loader in loaders_for(software)]]
        if version:
            facets.append([f'versions:{version}'])
        url = (f'https://api.modrinth.com/v2/search?limit=20&offset={offset}&index=relevance'
               f'&query={quote(query)}&facets={quote(json.dumps(facets))}')
        data = self.http.json(url)
        results = [{
            'source': 'modrinth', 'id': h.get('project_id'), 'name': h.get('title'), 'author': h.get('author'),
            'summary': (h.get('description') or '')[:300], 'downloads': h.get('downloads'),
            'icon': h.get('icon_url') or None, 'page': f"https://modrinth.com/{h.get('project_type', 'plugin')}/{h.get('slug')}",
            'installable': True, 'verified': True, 'note': None,
        } for h in data.get('hits', []) if h.get('project_id')]
        return {'results': results, 'total': data.get('total_hits', len(results))}

    def _search_hangar(self, query, software, version, offset):
        url = f'https://hangar.papermc.io/api/v1/projects?limit=20&offset={offset}&platform=PAPER&q={quote(query)}'
        if not query:
            url += '&sort=-downloads'
        if version:
            url += f'&version={quote(version)}'
        data = self.http.json(url)
        results = []
        for p in data.get('result', []):
            ns = p.get('namespace') or {}
            results.append({
                'source': 'hangar', 'id': str(p.get('id')), 'name': p.get('name'), 'author': ns.get('owner'),
                'summary': (p.get('description') or '')[:300], 'downloads': (p.get('stats') or {}).get('downloads'),
                'icon': p.get('avatarUrl') or None,
                'page': f"https://hangar.papermc.io/{quote(ns.get('owner', ''))}/{quote(ns.get('slug', ''))}",
                'installable': True, 'verified': True, 'note': None,
            })
        return {'results': results, 'total': (data.get('pagination') or {}).get('count', len(results))}

    def _search_spiget(self, query, software, version, offset):
        fields = 'id,name,tag,downloads,file,testedVersions,external,premium,icon,author'
        page = offset // 20 + 1
        if query:
            url = f'https://api.spiget.org/v2/search/resources/{quote(query, safe="")}?field=name&size=20&page={page}&sort=-downloads&fields={fields}'
        else:
            url = f'https://api.spiget.org/v2/resources/free?size=20&page={page}&sort=-downloads&fields={fields}'
        try:
            data = self.http.json(url)
        except MarketError as exc:
            if 'Not found' in str(exc):
                return {'results': [], 'total': 0}
            raise
        results = []
        for r in data if isinstance(data, list) else []:
            tested = r.get('testedVersions') or []
            if version and tested and _minor(version) not in {_minor(t) for t in tested} and version not in tested:
                continue
            premium, external = bool(r.get('premium')), bool(r.get('external')) or (r.get('file') or {}).get('type') == 'external'
            icon = (r.get('icon') or {}).get('data')
            results.append({
                'source': 'spiget', 'id': str(r.get('id')), 'name': r.get('name'), 'author': None,
                'summary': (r.get('tag') or '')[:300], 'downloads': r.get('downloads'),
                'icon': f'data:image/png;base64,{icon}' if icon and re.fullmatch(r'[A-Za-z0-9+/=]{16,200000}', icon) else None,
                'page': f"https://www.spigotmc.org/resources/{r.get('id')}/",
                'installable': not premium and not external, 'verified': False,
                'note': 'Premium resource: buy and download it on SpigotMC' if premium else
                        'Hosted outside SpigotMC: download it from the project page' if external else
                        'SpigotMC files have no published checksum',
                'tested': tested[-4:],
            })
        return {'results': results, 'total': None}

    # ---- versions -----------------------------------------------------------------------
    def versions(self, source: str, project: str, software: str, version: str | None) -> list[dict]:
        _validate(source, software, version)
        if not ID_RE.match(project or ''):
            raise MarketError('Invalid project id')
        key = json.dumps(['v', source, project, software, version])
        # Stable releases first; the sources already list newest first within each group.
        return self._cached(key, 120, lambda: sorted(getattr(self, f'_versions_{source}')(project, software, version),
                                                     key=lambda v: v['channel'].lower() != 'release'))

    def _versions_modrinth(self, project, software, version):
        url = f'https://api.modrinth.com/v2/project/{quote(project)}/version?loaders={quote(json.dumps(loaders_for(software)))}'
        if version:
            url += f'&game_versions={quote(json.dumps([version]))}'
        out = []
        for v in self.http.json(url)[:25]:
            files = v.get('files') or []
            f = next((f for f in files if f.get('primary')), files[0] if files else None)
            if not f or not str(f.get('filename', '')).lower().endswith('.jar') or not (f.get('hashes') or {}).get('sha512'):
                continue
            out.append({'id': v.get('id'), 'name': v.get('version_number') or v.get('name'), 'channel': (v.get('version_type') or 'release').capitalize(),
                        'game_versions': (v.get('game_versions') or [])[-6:], 'loaders': v.get('loaders') or [],
                        'filename': f['filename'], 'size': f.get('size'), 'published': v.get('date_published'),
                        'hash': ['sha512', f['hashes']['sha512']], 'url': f.get('url'), 'verified': True})
        return out

    def _versions_hangar(self, project, software, version):
        url = f'https://hangar.papermc.io/api/v1/projects/{quote(project)}/versions?limit=25&offset=0&platform=PAPER'
        if version:
            url += f'&platformVersion={quote(version)}'
        out = []
        for v in self.http.json(url).get('result', []):
            d = (v.get('downloads') or {}).get('PAPER') or {}
            info = d.get('fileInfo') or {}
            if d.get('externalUrl') or not d.get('downloadUrl') or not info.get('sha256Hash') or not str(info.get('name', '')).lower().endswith('.jar'):
                continue
            out.append({'id': v.get('name'), 'name': v.get('name'), 'channel': (v.get('channel') or {}).get('name') or 'Release',
                        'game_versions': ((v.get('platformDependencies') or {}).get('PAPER') or [])[-6:], 'loaders': ['paper'],
                        'filename': info['name'], 'size': info.get('sizeBytes'), 'published': v.get('createdAt'),
                        'hash': ['sha256', info['sha256Hash']], 'url': d['downloadUrl'], 'verified': True})
        return out

    def _versions_spiget(self, project, software, version):
        r = self.http.json(f'https://api.spiget.org/v2/resources/{quote(project)}?fields=id,name,file,premium,external,testedVersions,version,updateDate')
        file = r.get('file') or {}
        if r.get('premium') or r.get('external') or file.get('type') != '.jar':
            return []
        version_id = str((r.get('version') or {}).get('id') or 'latest')
        name = re.sub(r'-{2,}', '-', re.sub(r'[^A-Za-z0-9_.-]+', '-', str(r.get('name') or f'resource-{project}'))).strip('-.')[:80] or f'resource-{project}'
        return [{'id': version_id, 'name': 'Latest', 'channel': 'Release', 'game_versions': (r.get('testedVersions') or [])[-6:],
                 'loaders': ['spigot'], 'filename': f'{name}.jar', 'size': None, 'published': r.get('updateDate'),
                 'hash': None, 'url': f'https://api.spiget.org/v2/resources/{quote(project)}/download', 'verified': False}]

    # ---- install ------------------------------------------------------------------------
    def fetch(self, source: str, project: str, version_id: str, software: str, version: str | None, allow_unverified: bool) -> tuple[str, bytes, dict]:
        """Resolve the chosen file server-side, download it and verify it. Returns (filename, bytes, record)."""
        if not ID_RE.match(version_id or ''):
            raise MarketError('Invalid version id')
        self._cache.pop(json.dumps(['v', source, project, software, version]), None)
        chosen = next((v for v in self.versions(source, project, software, version) if str(v['id']) == str(version_id)), None)
        if not chosen:
            raise MarketError('That version is no longer offered for this server software and version')
        if not chosen['verified'] and not allow_unverified:
            raise MarketError('This file has no published checksum. Confirm installing an unverified file to continue')
        body = self.http.file(chosen['url'])
        if chosen['hash']:
            algorithm, expected = chosen['hash']
            actual = hashlib.new(algorithm, body).hexdigest()
            if actual.lower() != str(expected).lower():
                raise MarketError('Download failed its checksum; nothing was installed')
        filename = check_jar(body, chosen['filename'], kind_of(software))
        record = {'source': source, 'project': project, 'version': chosen['name'], 'version_id': str(version_id),
                  'sha256': hashlib.sha256(body).hexdigest(), 'verified': chosen['verified']}
        return filename, body, record

    def icon(self, url: str) -> tuple[bytes, str]:
        return self._cached(json.dumps(['icon', url]), 3600, lambda: self.http.icon(url))


def check_jar(body: bytes, filename: str, kind: str) -> str:
    name = Path(str(filename)).name
    name = re.sub(r'[^A-Za-z0-9_. -]+', '-', name).strip(' .-')
    if not name.lower().endswith('.jar'):
        name += '.jar'
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,123}\.jar', name, re.I):
        raise MarketError('The download has an unusable filename')
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as jar:
            names = set(jar.namelist())
            if not names or len(names) > 50000:
                raise MarketError('The download is not a valid JAR')
    except zipfile.BadZipFile as exc:
        raise MarketError('The download is not a valid JAR') from exc
    descriptors = ('plugin.yml', 'paper-plugin.yml') if kind == 'plugin' else ('mcmod.info', 'META-INF/mods.toml', 'META-INF/neoforge.mods.toml', 'fabric.mod.json', 'quilt.mod.json')
    if not names.intersection(descriptors):
        raise MarketError(f'The download does not contain a {kind} descriptor; nothing was installed')
    return name
