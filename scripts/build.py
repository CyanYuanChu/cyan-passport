#!/usr/bin/env python3
"""Build the native feature once, then package it for Grove and a standalone app."""
from pathlib import Path
import json,os,plistlib,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parent.parent;m=json.loads((ROOT/'module.json').read_text());build=ROOT/'build';build.mkdir(exist_ok=True)
sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
flags=['-parse-as-library','-swift-version','5','-O','-sdk',sdk,'-target','arm64-apple-macosx'+m['minMacOS']]
signer=os.environ.get('CODE_SIGN_IDENTITY','-')
def plist(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('wb') as f:plistlib.dump(value,f)
def sign(path):subprocess.run(['codesign','--force','--sign',signer,str(path)],check=True)
def widget(output,host=None):
 env=os.environ.copy()
 if host:env['CYAN_WIDGET_HOST_ID']=host
 subprocess.run([sys.executable,'-c','import runpy;runpy.run_path("scripts/widget_project.py",run_name="__main__")'],cwd=ROOT,env=env,check=True)
 with (build/(output+'-build.log')).open('w') as log:subprocess.run(['xcodebuild','-project','build/Widget.xcodeproj','-target','CyanGitHubWidgets','-configuration','Release','-sdk','macosx','ARCHS=arm64','CODE_SIGNING_ALLOWED=NO','CONFIGURATION_BUILD_DIR='+str(build/output)],cwd=ROOT,env=env,check=True,stdout=log,stderr=subprocess.STDOUT)
 return build/output/'CyanGitHubWidgets.appex'
plugin=build/m['moduleName']
if plugin.exists():shutil.rmtree(plugin)
c=plugin/'Contents';exe=c/'MacOS/CyanFeature';exe.parent.mkdir(parents=True)
shutil.copytree(ROOT/'Resources',c/'Resources',ignore=shutil.ignore_patterns('__pycache__','local','*.pem','token'))
shutil.copy2(ROOT/'module.json',c/'Resources/module.json')
plist(c/'Info.plist',dict(CFBundleIdentifier=m['pluginBundleID'],CFBundleExecutable='CyanFeature',CFBundleName=m['name']+' Feature',CFBundlePackageType='BNDL',CFBundleShortVersionString=m['version'].split('-')[0],CFBundleVersion='2',LSMinimumSystemVersion=m['minMacOS']))
sources=[p for p in sorted((ROOT/'Sources').glob('*.swift')) if p.name!='ModuleApp.swift']
subprocess.run(['xcrun','swiftc','-emit-library',*flags,'-module-name',m['id'].replace('-','_')+'_feature',*map(str,sources),'-o',str(exe)],check=True)
classic=None
if (ROOT/'Widget').exists():
 classic=widget('widget-products')
 host='io.github.cyanyuanchu.cyangrove.github-widgets';supportWidget=widget('widget-support-products',host)
 helper=c/'Resources/WidgetSupport/Cyan Grove GitHub Widgets.app';hc=helper/'Contents';hexe=hc/'MacOS/WidgetRegistration';hexe.parent.mkdir(parents=True);(hc/'Resources').mkdir();(hc/'PlugIns').mkdir()
 source=build/'WidgetRegistration.swift';source.write_text('import AppKit\n@main struct WidgetRegistration { @MainActor static func main() { let app = NSApplication.shared; app.setActivationPolicy(.accessory); _ = Timer.scheduledTimer(withTimeInterval:0.4,repeats:false) { _ in NSApp.terminate(nil) }; app.run() } }\n')
 subprocess.run(['xcrun','swiftc',*flags,str(source),'-o',str(hexe)],check=True)
 plist(hc/'Info.plist',dict(CFBundleIdentifier=host,CFBundleExecutable='WidgetRegistration',CFBundleName='Cyan GitHub Widgets',CFBundlePackageType='APPL',CFBundleShortVersionString=m['version'].split('-')[0],CFBundleVersion='2',LSMinimumSystemVersion='14.0',LSUIElement=True))
 (hc/'Resources/feature-version.txt').write_text(m['version']);shutil.copytree(supportWidget,hc/'PlugIns/CyanGitHubWidgets.appex');sign(hc/'PlugIns/CyanGitHubWidgets.appex');sign(helper)
sign(plugin)
app=build/m['appName']
if app.exists():shutil.rmtree(app)
c=app/'Contents';exe=c/'MacOS'/m['name'];exe.parent.mkdir(parents=True);(c/'Resources').mkdir();(c/'PlugIns').mkdir()
shutil.copy2(ROOT/'module.json',c/'Resources/module.json');shutil.copy2(ROOT/'Resources/CyanGroveLeaf.icns',c/'Resources/CyanGroveLeaf.icns');shutil.copytree(plugin,c/'PlugIns'/m['moduleName'])
plist(c/'Info.plist',dict(CFBundleIdentifier=m['bundleID'],CFBundleExecutable=m['name'],CFBundleName=m['name'],CFBundleDisplayName=m['name'],CFBundlePackageType='APPL',CFBundleShortVersionString=m['version'].split('-')[0],CFBundleVersion='2',LSMinimumSystemVersion=m['minMacOS'],CFBundleIconFile='CyanGroveLeaf',NSHighResolutionCapable=True,CFBundleURLTypes=[dict(CFBundleURLSchemes=[m['id']])]))
shell=['ModuleApp.swift','PluginAPI.swift','ModuleRuntime.swift','StartupManager.swift','UI.swift']
subprocess.run(['xcrun','swiftc',*flags,'-module-name',m['id'].replace('-','_')+'_shell',*[str(ROOT/'Sources'/name) for name in shell],'-o',str(exe)],check=True)
if classic:shutil.copytree(classic,c/'PlugIns/CyanGitHubWidgets.appex');sign(c/'PlugIns/CyanGitHubWidgets.appex')
sign(app);print('BUILD_OK',plugin,app)
