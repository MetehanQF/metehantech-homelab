from pathlib import Path
import subprocess,json
p=Path(__file__).parent
creds=json.loads((p/'credentials.json').read_text())
script='''import sys,json,re,pathlib,yaml,hashlib
from frigate.config import FrigateConfig
payload=json.load(sys.stdin)
p=pathlib.Path('/config/config.yml'); old=p.read_text()
assert yaml.safe_load(old)['mqtt']=={'enabled':False}, 'Unexpected MQTT config'
block=yaml.safe_dump({'mqtt':{'enabled':True,'host':'metehantech-mosquitto','port':1883,'user':'frigate','password':payload['password'],'client_id':'metehantech-frigate','topic_prefix':'frigate'}},sort_keys=False)
new=re.sub(r'^mqtt:\\n(?:[ \\t]+[^\\n]*\\n|\\n)*',block,old,count=1,flags=re.M)
a=yaml.safe_load(old); b=yaml.safe_load(new); a.pop('mqtt'); b.pop('mqtt'); assert a==b,'Non-MQTT change'
FrigateConfig.parse_yaml(new)
p.write_text(new)
print('Frigate config validated; only MQTT section changed.')
'''
r=subprocess.run(['docker','exec','-i','metehantech-frigate','python3','-c',script],input=json.dumps({'password':creds['frigate']}),text=True,capture_output=True)
if r.returncode: print('Config update failed; details withheld to protect secrets.');raise SystemExit(1)
print(r.stdout)
