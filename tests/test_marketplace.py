import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from panel.app import create_app
from panel.marketplace import Http, Marketplace, MarketError, check_jar, detect


def jar(*names):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name in names:
            archive.writestr(name, 'name: Test\nversion: 1\nmain: x.Y\n')
    return buffer.getvalue()


PLUGIN = jar('plugin.yml', 'x/Y.class')
NOT_A_PLUGIN = jar('README.txt')


class FakeSources:
    """Stands in for the real APIs; records every URL the panel asks for."""

    def __init__(self, plugin_bytes=PLUGIN, sha512=None):
        self.requests = []
        self.plugin_bytes = plugin_bytes
        self.sha512 = sha512 or hashlib.sha512(plugin_bytes).hexdigest()

    def __call__(self, request: httpx.Request):
        self.requests.append(str(request.url))
        host, path = request.url.host, request.url.path
        if host == 'api.modrinth.com' and path == '/v2/search':
            return httpx.Response(200, json={'total_hits': 1, 'hits': [{'project_id': 'abc123', 'slug': 'good', 'title': 'Good Plugin',
                                                                        'author': 'dev', 'description': 'Does good things', 'downloads': 42,
                                                                        'icon_url': 'https://cdn.modrinth.com/i.png', 'project_type': 'plugin'}]})
        if host == 'api.modrinth.com' and path == '/v2/project/abc123/version':
            return httpx.Response(200, json=[{'id': 'v1', 'version_number': '1.0.0', 'version_type': 'release', 'game_versions': ['1.21.4'],
                                              'loaders': ['paper'], 'date_published': '2026-01-01',
                                              'files': [{'primary': True, 'filename': 'Good-1.0.0.jar', 'size': len(self.plugin_bytes),
                                                         'url': 'https://cdn.modrinth.com/data/abc123/Good-1.0.0.jar', 'hashes': {'sha512': self.sha512}}]}])
        if host == 'cdn.modrinth.com' and path == '/data/abc123/Good-1.0.0.jar':
            return httpx.Response(200, content=self.plugin_bytes)
        if host == 'api.spiget.org' and path == '/v2/resources/77':
            return httpx.Response(200, json={'id': 77, 'name': 'Old Plugin', 'file': {'type': '.jar'}, 'premium': False, 'external': False,
                                             'testedVersions': ['1.21'], 'version': {'id': 900}})
        if host == 'api.spiget.org' and path == '/v2/resources/77/download':
            return httpx.Response(302, headers={'location': 'https://cdn.spiget.org/file/spiget-resources/77.jar'})
        if host == 'cdn.spiget.org':
            return httpx.Response(200, content=self.plugin_bytes)
        if host == 'api.spiget.org' and path == '/v2/resources/66':
            return httpx.Response(200, json={'id': 66, 'name': 'Sneaky', 'file': {'type': '.jar'}, 'premium': False, 'external': False, 'version': {'id': 1}})
        if host == 'api.spiget.org' and path == '/v2/resources/66/download':
            return httpx.Response(302, headers={'location': 'https://evil.example/payload.jar'})
        return httpx.Response(404, json={})


def market(fake):
    return Marketplace(Http(httpx.MockTransport(fake)))


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = json.loads(Path('config.example.json').read_text())
    config.update(data=str(tmp_path / 'data'), backups=str(tmp_path / 'backups'), origin='http://testserver', secure_cookie=False)
    (tmp_path / 'backups').mkdir()
    for sid, srv in config['servers'].items():
        srv['root'] = str(tmp_path / sid)
        Path(srv['root']).mkdir()
    monkeypatch.setattr('panel.system.unit_status', lambda unit: {'ActiveState': 'inactive', 'pid': 0})
    monkeypatch.setattr('panel.minecraft.status', lambda port: {'version': 'test', 'players': {'online': 0, 'max': 10}})
    fake = FakeSources()
    app = create_app(config, market=market(fake))
    app.state.auth.user('admin', 'correct horse battery staple', 'admin')
    app.state.auth.user('viewer', 'correct horse battery staple', 'viewer')
    return app, config, fake


def signin(client, name='admin'):
    response = client.post('/api/login', json={'username': name, 'password': 'correct horse battery staple'}, headers={'Origin': 'http://testserver'})
    assert response.status_code == 200
    client.headers.update({'Origin': 'http://testserver', 'X-CSRF-Token': response.json()['csrf']})


INSTALL = {'source': 'modrinth', 'project': 'abc123', 'version_id': 'v1', 'software': 'paper', 'version': '1.21.4', 'confirmed': True}


def test_detects_software_and_version(tmp_path):
    (tmp_path / 'version_history.json').write_text(json.dumps({'currentVersion': 'git-Paper-123 (MC: 1.21.4)'}))
    found = detect({'root': str(tmp_path), 'jar': 'server.jar', 'legacy': False})
    assert (found['software'], found['version'], found['kind']) == ('paper', '1.21.4', 'plugin')
    assert found['sources'] == ['modrinth', 'hangar', 'spiget']
    forge = detect({'root': str(tmp_path / 'none'), 'jar': 'forge-1.12.2-14.23.5.2860.jar', 'legacy': True})
    assert (forge['software'], forge['version'], forge['kind'], forge['sources']) == ('forge', '1.12.2', 'mod', ['modrinth'])
    override = detect({'root': str(tmp_path), 'software': 'purpur', 'minecraft_version': '1.21.1'})
    assert (override['software'], override['version'], override['detected_from']) == ('purpur', '1.21.1', 'configuration')


def test_search_filters_by_loader_and_version():
    fake = FakeSources()
    result = market(fake).search('modrinth', 'good', 'paper', '1.21.4')
    assert result['results'][0]['name'] == 'Good Plugin' and result['results'][0]['verified']
    facets = json.loads(httpx.URL(fake.requests[0]).params['facets'])
    assert facets == [['project_type:plugin'], ['categories:paper', 'categories:spigot', 'categories:bukkit'], ['versions:1.21.4']]
    with pytest.raises(MarketError):
        market(fake).search('hangar', 'x', 'forge', '1.12.2')  # Hangar has no Forge mods


def test_install_verifies_and_writes_plugin(setup, tmp_path):
    app, config, _ = setup
    with TestClient(app) as client:
        signin(client)
        response = client.post('/api/servers/survival/marketplace/install', json=INSTALL)
        assert response.status_code == 200, response.text
        installed = Path(config['servers']['survival']['root']) / 'plugins' / 'Good-1.0.0.jar'
        assert installed.read_bytes() == PLUGIN
        assert response.json()['sha256'] == hashlib.sha256(PLUGIN).hexdigest()
        with app.state.auth.db() as db:
            detail = db.execute("SELECT detail FROM audit WHERE action='extension.install'").fetchone()[0]
        assert 'modrinth:abc123@1.0.0' in detail
        # The same file twice is a conflict, not an overwrite.
        assert client.post('/api/servers/survival/marketplace/install', json=INSTALL).status_code == 409


def test_viewer_and_unconfirmed_installs_are_refused(setup):
    app, _, _ = setup
    with TestClient(app) as client:
        signin(client, 'viewer')
        assert client.get('/api/servers/survival/marketplace/search', params={'source': 'modrinth', 'software': 'paper', 'q': 'good'}).status_code == 200
        assert client.post('/api/servers/survival/marketplace/install', json=INSTALL).status_code == 403
    with TestClient(app) as client:
        signin(client)
        assert client.post('/api/servers/survival/marketplace/install', json={**INSTALL, 'confirmed': False}).status_code == 400


def test_checksum_mismatch_installs_nothing(tmp_path):
    fake = FakeSources(sha512='0' * 128)
    with pytest.raises(MarketError, match='checksum'):
        market(fake).fetch('modrinth', 'abc123', 'v1', 'paper', '1.21.4', False)


def test_jar_without_plugin_descriptor_is_refused():
    fake = FakeSources(plugin_bytes=NOT_A_PLUGIN)
    with pytest.raises(MarketError, match='descriptor'):
        market(fake).fetch('modrinth', 'abc123', 'v1', 'paper', '1.21.4', False)


def test_unverified_spiget_needs_explicit_consent():
    fake = FakeSources()
    with pytest.raises(MarketError, match='no published checksum'):
        market(fake).fetch('spiget', '77', '900', 'paper', '1.21.4', False)
    filename, body, record = market(fake).fetch('spiget', '77', '900', 'paper', '1.21.4', True)
    assert filename == 'Old-Plugin.jar' and body == PLUGIN and record['verified'] is False


def test_redirect_to_unlisted_host_is_refused():
    fake = FakeSources()
    with pytest.raises(MarketError, match='outside the plugin sources'):
        market(fake).fetch('spiget', '66', '1', 'paper', '1.21.4', True)
    assert not any('evil.example' in url for url in fake.requests)


def test_icon_proxy_only_fetches_cdn_images():
    fake = FakeSources()
    with pytest.raises(MarketError):
        market(fake).icon('https://evil.example/x.png')
    with pytest.raises(MarketError):
        market(fake).icon('http://cdn.modrinth.com/x.png')


def test_check_jar_cleans_filenames():
    assert check_jar(PLUGIN, '../../etc/Plugin v2.jar', 'plugin') == 'Plugin v2.jar'
    with pytest.raises(MarketError):
        check_jar(b'not a zip', 'x.jar', 'plugin')
