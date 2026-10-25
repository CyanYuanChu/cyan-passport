#!/usr/bin/env python3
"""Build a self-contained native module from this repository only."""
from pathlib import Path
import json,os,plistlib,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parent.parent
m=json.loads((ROOT/'module.json').read_text());build=ROOT/'build';build.mkdir(exist_ok=True)
app=build/m['appName'];contents=app/'Contents';exe=contents/'MacOS'/m['name'];resources=contents/'Resources'
if app.exists():shutil.rmtree(app)
exe.parent.mkdir(parents=True);shutil.copytree(ROOT/'Resources',resources,ignore=shutil.ignore_patterns('__pycache__','local','*.pem','token'))
shutil.copy2(ROOT/'module.json',resources/'module.json')
info=dict(CFBundleIdentifier=m['bundleID'],CFBundleExecutable=m['name'],CFBundleName=m['name'],CFBundleDisplayName=m['name'],CFBundlePackageType='APPL',CFBundleShortVersionString=m['version'].split('-')[0],CFBundleVersion='1',LSMinimumSystemVersion=m['minMacOS'],NSHighResolutionCapable=True,CFBundleIconFile='CyanGroveLeaf',CFBundleURLTypes=[dict(CFBundleURLSchemes=[m['id']])])
with (contents/'Info.plist').open('wb') as f:plistlib.dump(info,f)
sources=sorted((ROOT/'Sources').glob('*.swift'))
sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
subprocess.run(['xcrun','swiftc','-parse-as-library','-swift-version','5','-O','-sdk',sdk,'-target','arm64-apple-macosx'+m['minMacOS'],'-module-name',m['id'].replace('-','_'),*map(str,sources),'-o',str(exe)],check=True)
# GitHub 软件保留独立 WidgetKit 扩展；Xcode 仅用于构建扩展。
if (ROOT/'Widget').exists():
 subprocess.run([sys.executable,'-c','import runpy;runpy.run_path("scripts/widget_project.py",run_name="__main__")'],cwd=ROOT,check=True)
 subprocess.run(['xcodebuild','-project','build/Widget.xcodeproj','-target','CyanGitHubWidgets','-configuration','Release','-sdk','macosx','ARCHS=arm64','CODE_SIGNING_ALLOWED=NO','CONFIGURATION_BUILD_DIR='+str(build/'widget-products')],cwd=ROOT,check=True,stdout=(build/'widget-build.log').open('w'),stderr=subprocess.STDOUT)
 plug=contents/'PlugIns';plug.mkdir();shutil.copytree(build/'widget-products/CyanGitHubWidgets.appex',plug/'CyanGitHubWidgets.appex')
 subprocess.run(['codesign','--force','--sign',os.environ.get('CODE_SIGN_IDENTITY','-'),str(plug/'CyanGitHubWidgets.appex')],check=True)
subprocess.run(['codesign','--force','--sign',os.environ.get('CODE_SIGN_IDENTITY','-'),str(app)],check=True)
print('BUILD_OK',app)
