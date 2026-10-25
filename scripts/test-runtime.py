from pathlib import Path
import json,subprocess,time,socket,stat,os
R=Path(__file__).resolve().parent.parent;m=json.loads((R/'module.json').read_text());exe=R/'build'/m['appName']/'Contents/MacOS'/m['name']
def request(action):
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
  s.settimeout(4);s.connect('/tmp/cyan-modules-'+str(os.getuid())+'/'+m['id']+'.sock');s.sendall(json.dumps(dict(protocolVersion=1,action=action)).encode()+b'\n');data=b''
  while b'\n' not in data:
   chunk=s.recv(4096)
   if not chunk:raise ConnectionError('control closed')
   data+=chunk
  return json.loads(data.split(b'\n')[0])
log=(R/'build/runtime-test.log').open('w');p=subprocess.Popen([str(exe),'--background','--no-autostart','--no-shortcut','--no-widget-registration'],stdout=log,stderr=log)
try:
 result=None
 for _ in range(70):
  try:result=request('status');break
  except (OSError,ValueError):time.sleep(.1)
 assert result and result['ok'] and result['featureAPI']==2 and result['pid']==p.pid
 assert stat.S_IMODE(os.stat('/tmp/cyan-modules-'+str(os.getuid())+'/'+m['id']+'.sock').st_mode)==0o600
 duplicate=subprocess.run([str(exe),'--background','--no-autostart','--no-shortcut','--no-widget-registration'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12)
 assert duplicate.returncode==0 and request('status')['pid']==p.pid
 assert request('arbitrary-shell')['ok'] is False
 assert request('refresh')['ok']
 assert request('quit')['ok'];p.wait(timeout=12)
 assert not Path('/tmp/cyan-modules-'+str(os.getuid())+'/'+m['id']+'.sock').exists()
 print('STANDALONE_RUNTIME_OK',m['id'],'shared-native-bundle single-instance control clean-stop')
finally:
 if p.poll() is None:p.terminate();p.wait(timeout=10)
 log.close()
