import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from panel.auth import Auth
from panel.serve import proxy_options
from test_security import setup,signin


def test_rename_preserves_password_and_revokes_sessions(tmp_path):
    auth=Auth(tmp_path/'db')
    auth.user('admin','a long private password','admin')
    token,_=auth.login('admin','a long private password','local')
    auth.rename('admin','Owner')
    assert auth.session(token) is None
    assert auth.login('admin','a long private password','old') is None
    assert auth.login('Owner','a long private password','new') is not None
    auth.rename('admin','Owner')
    auth.user('Other','another long password','admin')
    with pytest.raises(ValueError):auth.rename('Owner','Other')


def test_invite_is_hashed_one_use_and_admin(tmp_path):
    auth=Auth(tmp_path/'db')
    token=auth.invite('Alex','admin','Owner')
    with auth.db() as db:
        row=db.execute('SELECT * FROM invites').fetchone()
        assert row['token']!=token and row['token']==auth.digest(token)
    assert auth.redeem(token,'Alex chooses this privately','ip')=='Alex'
    login,_=auth.login('Alex','Alex chooses this privately','ip')
    assert auth.session(login)['role']=='admin'
    with pytest.raises(ValueError):auth.redeem(token,'try reusing this invitation','ip')


def test_expired_invitation_and_rotation(tmp_path):
    auth=Auth(tmp_path/'db')
    old=auth.invite('Sam','admin','Owner')
    current=auth.invite('Sam','admin','Owner')
    with pytest.raises(ValueError):auth.redeem(old,'this is a sufficiently long password','ip')
    with auth.db() as db:db.execute('UPDATE invites SET expires=?',(time.time()-1,))
    with pytest.raises(ValueError):auth.redeem(current,'this is a sufficiently long password','ip')


def test_invite_endpoints_require_admin_and_csrf(setup):
    app,_=setup
    with TestClient(app) as client:
        assert client.get('/api/accounts').status_code==401
        signin(client,'viewer')
        assert client.get('/api/accounts').status_code==403
        assert client.post('/api/invites',json={'username':'Alex','role':'admin'}).status_code==403
        signin(client)
        response=client.post('/api/invites',json={'username':'Alex','role':'admin'})
        assert response.status_code==200
        token=response.json()['url'].split('#invite=')[1]
        client.post('/api/logout')
        assert client.post('/api/invites/redeem',json={'token':token,'password':'long private Alex password'},headers={'Origin':'http://evil'}).status_code==403
        response=client.post('/api/invites/redeem',json={'token':token,'password':'long private Alex password'},headers={'Origin':'http://testserver'})
        assert response.status_code==200
        result=client.post('/api/login',json={'username':'Alex','password':'long private Alex password'},headers={'Origin':'http://testserver'})
        assert result.status_code==200
        assert client.get('/api/me').json()['role']=='admin'
        assert client.post('/api/servers/survival/players',json={'action':'op','player':'invalid name','confirmed':True},headers={'X-CSRF-Token':result.json()['csrf']}).status_code==400
        with app.state.auth.db() as db:
            assert all(token not in row['detail'] for row in db.execute('SELECT detail FROM audit'))


def test_public_mode_requires_secure_configuration(setup):
    from panel.app import create_app
    _,config=setup
    with pytest.raises(ValueError):create_app({**config,'public_access':True})
    with pytest.raises(ValueError):proxy_options({'trusted_proxies':['*']})
    assert proxy_options({'trusted_proxies':['127.0.0.1']})=={'proxy_headers':True,'forwarded_allow_ips':['127.0.0.1']}


def test_public_requests_require_correct_host_and_https(setup):
    from panel.app import create_app
    _,config=setup
    app=create_app({**config,'public_access':True,'bind':'127.0.0.1','secure_cookie':True,'origin':'https://panel.example.ts.net'})
    with TestClient(app,base_url='https://panel.example.ts.net') as client:
        assert client.get('/api/me').status_code==401
        assert client.get('/api/me',headers={'Host':'attacker.example'}).status_code==400
    with TestClient(app,base_url='http://panel.example.ts.net') as client:
        assert client.get('/api/me').status_code==426


def test_authentication_body_limit_and_http_rate_limit(setup):
    app,_=setup
    with TestClient(app) as client:
        assert client.post('/api/login',json={'username':'x','password':'x'*20000},headers={'Origin':'http://testserver'}).status_code==413
        for _ in range(8):
            assert client.post('/api/login',json={'username':'missing','password':'wrong'},headers={'Origin':'http://testserver'}).status_code==401
        response=client.post('/api/login',json={'username':'missing','password':'wrong'},headers={'Origin':'http://testserver'})
        assert response.status_code==429 and response.headers['retry-after']=='900'


def test_only_local_proxy_can_supply_forwarded_headers(setup):
    from panel.app import create_app
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    _,config=setup
    app=create_app({**config,'public_access':True,'bind':'127.0.0.1','secure_cookie':True,'origin':'https://panel.example.ts.net'})
    proxied=ProxyHeadersMiddleware(app,trusted_hosts=['127.0.0.1'])
    headers={'Host':'panel.example.ts.net','X-Forwarded-Proto':'https','X-Forwarded-For':'203.0.113.10'}
    with TestClient(proxied,base_url='http://panel.example.ts.net',client=('127.0.0.1',5000)) as client:
        assert client.get('/api/me',headers=headers).status_code==401
    with TestClient(proxied,base_url='http://panel.example.ts.net',client=('192.0.2.10',5000)) as client:
        assert client.get('/api/me',headers=headers).status_code==426


@pytest.mark.skipif(__import__('os').name!='posix',reason='POSIX group ownership semantics')
def test_atomic_edit_retains_shared_group_access(tmp_path,monkeypatch):
    import os
    from panel.storage import atomic_write
    target=tmp_path/'settings.cfg'
    target.write_text('original')
    os.chmod(target,0o640)
    previous=target.stat()
    monkeypatch.setattr('panel.storage.os.geteuid',lambda:previous.st_uid+1)
    atomic_write(target,b'updated')
    assert target.stat().st_gid==previous.st_gid
    assert target.stat().st_mode & 0o060 == 0o060
