#!/usr/bin/env python3
from pathlib import Path
import json,subprocess,hashlib
R=Path(__file__).resolve().parent.parent
m=json.loads((R/'module.json').read_text());out=R/'build/release';out.mkdir(exist_ok=True)
name=m['name'].replace(' ','-')+'-macOS-arm64.zip';target=out/name
if target.exists():target.unlink()
subprocess.run(['ditto','-c','-k','--keepParent',str(R/'build'/m['appName']),str(target)],check=True)
m.update(sha256=hashlib.sha256(target.read_bytes()).hexdigest(),assetName=name)
(out/'module.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
(out/'SHA256SUMS').write_text(m['sha256']+'  '+name+'\n')
print('PACKAGED',m['id'],m['sha256'])
