#!/usr/bin/env python3
"""Read-only verification of the Home Assistant deployment.

Run manually after a planned reboot. Addresses come from this repository's
configuration (config.env / environment); nothing is hard-coded.
"""
import json, subprocess, urllib.request

import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env

LAN = env("PRIMARY_NODE_IP")
TS = env("PRIMARY_NODE_TAILSCALE_IP")

c=json.loads(subprocess.check_output(['docker','inspect','metehantech-homeassistant']))[0]
assert c['State']['Running'], 'Container stopped'
assert c['State'].get('Health',{}).get('Status')=='healthy', 'Not healthy'
assert c['HostConfig']['RestartPolicy']['Name']=='unless-stopped'
listeners=subprocess.check_output(['ss','-Hlnt','sport = :8123'],text=True)
addresses={line.split()[3] for line in listeners.splitlines()}
assert addresses=={'127.0.0.1:8123', LAN+':8123', TS+':8123'}, addresses
http=json.loads(subprocess.check_output(['docker','exec','metehantech-homeassistant','cat','/config/.storage/http']))['data']
assert http['pending'] is None
assert set(http['stable']['server_host'])=={'127.0.0.1', LAN, TS}
assert subprocess.check_output(['systemctl','is-enabled','docker'],text=True).strip()=='enabled'
for url in ['http://127.0.0.1:8123/', 'http://'+LAN+':8123/', 'http://'+TS+':8123/', 'http://127.0.0.1:5400/api/version','http://127.0.0.1:5300/status.php','http://127.0.0.1:5200/api/status']:
 with urllib.request.urlopen(url,timeout=15) as r:
  assert r.status==200
 print('OK',url)
print('PASS; started:',c['State']['StartedAt'])
