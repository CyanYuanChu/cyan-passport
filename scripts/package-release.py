#!/usr/bin/env python3
from pathlib import Path
import json,subprocess,hashlib
R=Path(__file__).resolve().parent.parent;m=json.loads((R/'module.json').read_text());out=R/'build/release';out.mkdir(exist_ok=True)
def package(path,name):
 dest=out/name
 if dest.exists():dest.unlink()
 subprocess.run(['ditto','-c','-k','--keepParent',str(path),str(dest)],check=True)
 return hashlib.sha256(dest.read_bytes()).hexdigest()
base=m['name'].replace(' ','-');native=base+'-module-macOS-arm64.zip';standalone=base+'-macOS-arm64.zip'
sha=package(R/'build'/m['moduleName'],native);appsha=package(R/'build'/m['appName'],standalone)
m.update(assetName=native,sha256=sha,standaloneAssetName=standalone,standaloneSha256=appsha)
(out/'module.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
(out/'SHA256SUMS').write_text(sha+'  '+native+'\n'+appsha+'  '+standalone+'\n')
print('PACKAGED_NATIVE_AND_STANDALONE',m['id'])
