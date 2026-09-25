from pathlib import Path
import subprocess,json
p=Path(__file__).parent
script='''import paho.mqtt.client as mqtt,json,sys,time
creds=json.load(sys.stdin); received={}; connected=[]
c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='metehantech-verification')
c.username_pw_set('probe',creds['probe'])
def on_connect(client,userdata,flags,reason,props):
 connected.append(not reason.is_failure)
 if not reason.is_failure: client.subscribe([('frigate/#',0),('homeassistant/status',0)])
def on_message(client,userdata,msg):
 topic=msg.topic; payload=msg.payload.decode(errors='replace')
 received[topic]=payload if topic.endswith(('/available','/state','/status')) else '[payload received]'
c.on_connect=on_connect;c.on_message=on_message;c.connect('127.0.0.1',1883);c.loop_start()
time.sleep(12);c.disconnect();c.loop_stop()
print(json.dumps({'connected':connected,'topics':received},indent=2))
'''
r=subprocess.run(['docker','exec','-i','metehantech-homeassistant','python3','-c',script],input=(p/'credentials.json').read_text(),text=True,capture_output=True)
print(r.stdout if r.returncode==0 else 'MQTT probe failed; raw error withheld');raise SystemExit(r.returncode)
