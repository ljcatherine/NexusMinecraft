import json
import os
from pathlib import Path
import uvicorn


def proxy_options(config):
    trusted = config.get('trusted_proxies',[])
    if not isinstance(trusted,list) or any(ip not in ('127.0.0.1','::1') for ip in trusted):
        raise ValueError('Only explicitly listed loopback proxies can be trusted')
    return {'proxy_headers':bool(trusted),'forwarded_allow_ips':trusted}

if __name__ == '__main__':
    config = json.loads(Path(os.environ.get('PS5_PANEL_CONFIG','/etc/ps5-panel/config.json')).read_text())
    uvicorn.run('panel.app:create_app', factory=True, host=config['bind'], port=config['port'], workers=1, **proxy_options(config), access_log=False, ws_max_size=65536)
