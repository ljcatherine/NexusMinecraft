import json
import socket
import struct
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from panel.app import create_app
from panel.auth import Auth
from panel.storage import safe_path, update_properties, atomic_write
from panel.rcon import command, receive, send


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = json.loads(Path('config.example.json').read_text())
    config.update(data=str(tmp_path/'data'),backups=str(tmp_path/'backups'),origin='http://testserver',secure_cookie=False)
    (tmp_path/'backups').mkdir()
    for sid,srv in config['servers'].items():
        srv['root'] = str(tmp_path/sid)
        root = Path(srv['root'])
        root.mkdir()
        (root/'server.properties').write_text('# keep\nmotd=Test\nenable-rcon=true\nrcon.password=DO-NOT-EXPOSE\nmax-players=10\n')
        (root/'config.json').write_text('{"original":true}')
        (root/'world').mkdir()
        (root/'world'/'level.dat').write_bytes(b'world')
    monkeypatch.setattr('panel.system.unit_status',lambda unit:{'ActiveState':'inactive','pid':0})
    monkeypatch.setattr('panel.minecraft.status',lambda port:{'version':'test','players':{'online':0,'max':10}})
    app = create_app(config)
    app.state.auth.user('admin','correct horse battery staple','admin')
    app.state.auth.user('viewer','correct horse battery staple','viewer')
    return app,config


def signin(client, name='admin'):
    response = client.post('/api/login',json={'username':name,'password':'correct horse battery staple'},headers={'Origin':'http://testserver'})
    assert response.status_code == 200
    csrf = response.json()['csrf']
    client.headers.update({'Origin':'http://testserver','X-CSRF-Token':csrf})


def test_auth_csrf_and_expiration(setup):
    app,_ = setup
    with TestClient(app) as client:
        assert client.get('/api/dashboard').status_code == 401
        assert client.post('/api/login',json={'username':'admin','password':'x'}).status_code == 403
        signin(client)
        assert client.get('/api/me').json()['role'] == 'admin'
        client.headers['X-CSRF-Token']='wrong'
        assert client.post('/api/logout').status_code == 403
        with app.state.auth.db() as db:
            db.execute('UPDATE sessions SET expires=0')
        assert client.get('/api/me').status_code == 401


def test_viewer_cannot_mutate(setup):
    app,_ = setup
    with TestClient(app) as client:
        signin(client,'viewer')
        for endpoint,body in [('/servers/survival/power/start',{}),('/servers/survival/command',{'command':'stop'}),('/servers/survival/files',{'path':'x.txt','text':'x'}),('/servers/survival/players',{'action':'op','player':'Steve','confirmed':True}),('/backups/run',{})]:
            assert client.post('/api'+endpoint,json=body).status_code == 403


def test_files_and_secrets(setup):
    app,config=setup
    with TestClient(app) as client:
        signin(client)
        assert client.get('/api/servers/survival/file',params={'path':'../skyfactory/server.properties'}).status_code == 400
        assert client.get('/api/servers/survival/file',params={'path':'server.properties'}).status_code == 400
        response=client.get('/api/servers/survival/settings')
        assert 'DO-NOT-EXPOSE' not in response.text
        old=client.get('/api/servers/survival/file',params={'path':'config.json'}).json()
        assert client.post('/api/servers/survival/files',json={'path':'config.json','text':'invalid','revision':old['revision']}).status_code == 400
        assert client.post('/api/servers/survival/files',json={'path':'config.json','text':'{}','revision':'stale'}).status_code == 409
        assert client.post('/api/servers/survival/files',json={'path':'config.json','text':'{"new":true}','revision':old['revision']}).status_code == 200
        assert list((Path(config['data'])/'edits'/'survival').iterdir())
        assert client.post('/api/servers/survival/files',json={'path':'world/level.dat','operation':'delete','confirmed':True}).status_code == 400
        assert client.put('/api/servers/skyfactory/settings',json={'values':{'simulation-distance':'8'}}).status_code == 400
        assert client.put('/api/servers/survival/settings',json={'values':{'rcon.password':'exposed'}}).status_code == 400


def test_viewer_cannot_read_server_files(setup):
    app,_=setup
    with TestClient(app) as client:
        signin(client,'viewer')
        assert client.get('/api/servers/survival/files').status_code == 200
        assert client.get('/api/servers/survival/file',params={'path':'config.json'}).status_code == 403
        assert client.get('/api/servers/survival/download',params={'path':'config.json'}).status_code == 403


def test_admin_can_install_plugin_jar_to_server_extension_folder(setup):
    import io
    import zipfile
    app,config=setup
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as jar:
        jar.writestr('plugin.yml','name: Example\nversion: 1.0\nmain: example.Main\n')
    with TestClient(app) as client:
        signin(client)
        response=client.post('/api/servers/survival/extensions',data={'confirmed':'true'},files={'file':('Example.jar',archive.getvalue(),'application/java-archive')})
        assert response.status_code == 200
        assert response.json() == {'ok':True,'name':'Example.jar','directory':'plugins','size':len(archive.getvalue()),'restart_required':True}
        assert (Path(config['servers']['survival']['root'])/'plugins'/'Example.jar').is_file()
        assert client.get('/api/servers/survival/extensions').json()[0]['name']=='Example.jar'


def test_extension_install_requires_admin_confirmation_and_safe_jar(setup):
    import io
    import zipfile
    app,_=setup
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as jar: jar.writestr('mods.toml','modLoader="javafml"')
    with TestClient(app) as client:
        signin(client,'viewer')
        assert client.post('/api/servers/skyfactory/extensions',data={'confirmed':'true'},files={'file':('Example.jar',archive.getvalue())}).status_code == 403
        signin(client)
        assert client.post('/api/servers/skyfactory/extensions',data={'confirmed':'false'},files={'file':('Example.jar',archive.getvalue())}).status_code == 400
        assert client.post('/api/servers/skyfactory/extensions',data={'confirmed':'true'},files={'file':('..\\escape.jar',archive.getvalue())}).status_code == 400
        invalid=client.post('/api/servers/skyfactory/extensions',data={'confirmed':'true'},files={'file':('bad.jar',b'not a jar')})
        assert invalid.status_code == 400
        assert client.post('/api/servers/skyfactory/upload',params={'path':'mods/Example.jar'},files={'file':('Example.jar',archive.getvalue())}).status_code == 400
        installed=client.post('/api/servers/skyfactory/extensions',data={'confirmed':'true'},files={'file':('Example.jar',archive.getvalue())})
        assert installed.status_code == 200 and installed.json()['directory']=='mods'
        duplicate=client.post('/api/servers/skyfactory/extensions',data={'confirmed':'true'},files={'file':('Example.jar',archive.getvalue())})
        assert duplicate.status_code == 409


def test_upload_request_size_is_rejected_before_multipart_parse(setup):
    app,_=setup
    with TestClient(app) as client:
        signin(client)
        response=client.post('/api/servers/survival/extensions',content=b'',headers={'Content-Length':str(65*1024*1024+1)})
        assert response.status_code == 413


def test_symlink_escape(tmp_path):
    root=tmp_path/'root';root.mkdir()
    outside=tmp_path/'outside';outside.mkdir()
    try:
        (root/'escape').symlink_to(outside,target_is_directory=True)
    except OSError:
        pytest.skip('Symlink creation requires Windows developer mode; run on Debian too')
    with pytest.raises(ValueError):
        safe_path(root,'escape/file')


def test_properties_preserved(tmp_path):
    assert update_properties('# comment\nmotd=old\nfoo=bar\n',{'motd':'new'}) == '# comment\nmotd=new\nfoo=bar\n'
    target=tmp_path/'test.txt'
    atomic_write(target,b'new')
    assert target.read_bytes()==b'new'


def test_login_rate_limit(tmp_path):
    auth=Auth(tmp_path/'db')
    for _ in range(8):
        assert auth.login('missing','wrong','127.0.0.1') is None
    with pytest.raises(ValueError):
        auth.login('missing','wrong','127.0.0.1')


def test_websocket_requires_origin_and_session(setup):
    app,_=setup
    with TestClient(app) as client:
        from starlette.websockets import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/live'):
                pass
        signin(client)
        with client.websocket_connect('/api/live',headers={'Origin':'http://testserver'}) as ws:
            assert 'host' in ws.receive_json()
        client.post('/api/logout')
        assert client.get('/api/me').status_code==401


def test_rcon_fragmentation_and_multiframe():
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen()
    port=listener.getsockname()[1]
    failures=[]
    def fake_server():
        try:
            with listener.accept()[0] as sock:
                ident,kind,password=receive(sock)
                assert kind==3 and password==b'secret'
                send(sock,ident,0,'')
                send(sock,ident,2,'')
                cid,_,text=receive(sock)
                barrier,_,_=receive(sock)
                assert text==b'list'
                send(sock,cid,0,'one ')
                send(sock,cid,0,'two')
                send(sock,barrier,0,'Unknown command')
        except BaseException as exc:
            failures.append(exc)
        finally:
            listener.close()
    thread=threading.Thread(target=fake_server);thread.start()
    assert command(port,'secret','list')=='one two'
    thread.join(timeout=5)
    assert not failures


def test_archive_traversal_rejected(setup,tmp_path):
    import io,tarfile
    app,config=setup
    with tarfile.open(Path(config['backups'])/'evil.tar.gz','w:gz') as archive:
        member=tarfile.TarInfo('../outside');member.size=1
        archive.addfile(member,io.BytesIO(b'x'))
    with TestClient(app) as client:
        signin(client)
        assert client.get('/api/backups/inspect',params={'path':'evil.tar.gz'}).status_code==400


def test_player_command_injection_rejected(setup):
    app,_=setup
    with TestClient(app) as client:
        signin(client)
        assert client.post('/api/servers/survival/players',json={'action':'op','player':'x\nstop','confirmed':True}).status_code==400
        assert client.post('/api/servers/survival/players',json={'action':'op','player':'Steve','confirmed':False}).status_code==400
