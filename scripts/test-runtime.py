from pathlib import Path
import json,subprocess,time,socket,stat,os
R=Path(__file__).resolve().parent.parent
def request(ident,action):
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
  s.settimeout(4);s.connect('/tmp/cyan-modules-'+str(os.getuid())+'/'+ident+'.sock')
  s.sendall(json.dumps(dict(protocolVersion=1,action=action)).encode()+b'\n');data=b''
  while b'\n' not in data:
   chunk=s.recv(4096)
   if not chunk:raise ConnectionError('server closed before response')
   data+=chunk
  return json.loads(data.split(b'\n')[0])
for repo in [R]:
 m=json.loads((repo/'module.json').read_text());exe=repo/'build'/m['appName']/'Contents/MacOS'/m['name']
 subprocess.run([str(repo/'scripts/check.sh')],check=True,stdout=(R/'build/runtime-checks.log').open('w'),stderr=subprocess.STDOUT)
 log=(R/'build/runtime-test.log').open('w')
 p=subprocess.Popen([str(exe),'--integrated','--no-autostart','--no-shortcut'],stdout=log,stderr=log)
 try:
  result=None
  for _ in range(60):
   try:result=request(m['id'],'status');break
   except (OSError,ValueError):time.sleep(.1)
  print('CONNECTED',m['id'],flush=True)
  assert result and result['id']==m['id'] and result['ok'],(m['id'],'no status')
  assert result['pid']==p.pid,(m['id'],'wrong process')
  assert stat.S_IMODE(os.stat('/tmp/cyan-modules-'+str(os.getuid())+'/'+m['id']+'.sock').st_mode)==0o600
  duplicate=subprocess.run([str(exe),'--integrated','--no-autostart','--no-shortcut'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=12)
  print('DUPLICATE_RETURNED',m['id'],flush=True)
  assert duplicate.returncode==0 and request(m['id'],'status')['pid']==p.pid
  assert request(m['id'],'arbitrary-shell-action')['ok'] is False
  assert request(m['id'],'standalone')['integrated'] is False
  assert request(m['id'],'integrated')['integrated'] is True
  assert request(m['id'],'quit')['ok'];p.wait(timeout=12)
  assert not Path('/tmp/cyan-modules-'+str(os.getuid())+'/'+m['id']+'.sock').exists()
  print('INTEGRATION_OK',m['id'],'single-instance socket-permissions unknown-action menu-control clean-stop',flush=True)
 finally:
  if p.poll() is None:p.terminate();p.wait(timeout=10)
  log.close()
