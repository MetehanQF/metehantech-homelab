from pathlib import Path
import json,subprocess,shutil,datetime,uuid
import sys as _sys, pathlib as _pl
for _d in _pl.Path(__file__).resolve().parents:
    if (_d / "homelab_config.py").exists():
        _sys.path.insert(0, str(_d)); break
from homelab_config import env  # values come from config.env / environment
p=Path(__file__).parent;b=Path((p/'backup-location').read_text());h=Path(env('HA_PROJECT_DIR'))
state=json.loads(subprocess.check_output(['docker','inspect','metehantech-homeassistant']))[0]['State'];assert not state['Running']
subprocess.run(['docker','cp','metehantech-homeassistant:/config/.storage/core.config_entries',str(b/'ha-core.config_entries')],check=True)
(b/'ha-core.config_entries').chmod(0o600)
shutil.copy2(h/'config/configuration.yaml',b/'ha-configuration.yaml')
d=json.loads((b/'ha-core.config_entries').read_text());assert not any(e['domain'] in ['mqtt','frigate'] for e in d['data']['entries'])
creds=json.loads((p/'credentials.json').read_text());now=datetime.datetime.now(datetime.timezone.utc).isoformat()
def entry(domain,data,options=None):
 return {'created_at':now,'data':data,'disabled_by':None,'discovery_keys':{},'domain':domain,'entry_id':uuid.uuid4().hex,'minor_version':1,'modified_at':now,'options':options or {},'pref_disable_new_entities':False,'pref_disable_polling':False,'source':'user','subentries':[],'title':'MetehanTech '+domain,'unique_id':None,'version':2}
d['data']['entries'].append(entry('mqtt',{'broker':'127.0.0.1','port':1883,'username':'homeassistant','password':creds['homeassistant']}))
d['data']['entries'].append(entry('frigate',{'url':'http://127.0.0.1:5400','validate_ssl':True}, {'rtsp_url_template':'rtsp://172.18.0.2:8554/{{ name }}_main'}))
f=p/'ha-config-entries.staged';f.write_text(json.dumps(d,indent=2));f.chmod(0o600)
subprocess.run(['docker','cp',str(f),'metehantech-homeassistant:/config/.storage/core.config_entries'],check=True)
# Refuse overwrite of an existing custom component.
cc=h/'config/custom_components';cc.mkdir(exist_ok=True);assert not (cc/'frigate').exists()
shutil.copytree(p/'staging/custom_components/frigate',cc/'frigate')
f=h/'config/configuration.yaml';s=f.read_text()
for key in ['media_source','stream']:
 if key+':' not in s: s+='\n'+key+':\n'
f.write_text(s)
print('Backed up HA configuration; MQTT and Frigate entries prepared without changing auth/users; official component installed.')
