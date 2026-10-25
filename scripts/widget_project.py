from pathlib import Path
import hashlib,json,plistlib
R=Path.cwd();M=json.loads((R/'module.json').read_text());P=R/'build/Widget.xcodeproj';P.mkdir(exist_ok=True);o={}
def add(n,isa,**kw):
 k=hashlib.sha1(n.encode()).hexdigest()[:24].upper();o[k]=dict(isa=isa,**kw);return k
paths=['Widget/GitGroveWidget.swift','Sources/Models.swift','Sources/PublicCalendar.swift','Sources/WidgetDesign.swift','Sources/Style.swift']
# UI.swift defines styling without extension-unsafe app code. Widget only needs Color(hex:).
style=R/'Sources/Style.swift'
if not style.exists():
 (R/'build/WidgetStyle.swift').write_text('import SwiftUI\nextension Color { init(hex: String) { let n = UInt64(hex.replacingOccurrences(of: "#", with: ""), radix: 16) ?? 0; self.init(.sRGB, red: Double((n >> 16) & 255)/255, green: Double((n >> 8) & 255)/255, blue: Double(n & 255)/255, opacity: 1) } }\n')
 paths[-1]='build/WidgetStyle.swift'
files=[add(p,'PBXFileReference',lastKnownFileType='sourcecode.swift',path=str(R/p),sourceTree='<absolute>') for p in paths]
build=[add('build'+p,'PBXBuildFile',fileRef=f) for p,f in zip(paths,files)]
product=add('product','PBXFileReference',explicitFileType='wrapper.app-extension',path='CyanGitHubWidgets.appex',sourceTree='BUILT_PRODUCTS_DIR')
group=add('group','PBXGroup',children=files+[product],sourceTree='<group>')
sources=add('sources','PBXSourcesBuildPhase',buildActionMask=2147483647,files=build,runOnlyForDeploymentPostprocessing=0)
frameworks=add('frameworks','PBXFrameworksBuildPhase',buildActionMask=2147483647,files=[],runOnlyForDeploymentPostprocessing=0)
info=R/'build/WidgetInfo.plist'
with info.open('wb') as f:plistlib.dump(dict(CFBundleExecutable='$(EXECUTABLE_NAME)',CFBundleIdentifier='$(PRODUCT_BUNDLE_IDENTIFIER)',CFBundleName='Cyan GitHub',CFBundlePackageType='XPC!',CFBundleShortVersionString='0.1.0',CFBundleVersion='1',NSExtension=dict(NSExtensionPointIdentifier='com.apple.widgetkit-extension')),f)
settings=dict(SDKROOT='macosx',MACOSX_DEPLOYMENT_TARGET='14.0',SWIFT_VERSION='5.0',PRODUCT_BUNDLE_IDENTIFIER=M['bundleID']+'.widgets',PRODUCT_NAME='CyanGitHubWidgets',INFOPLIST_FILE=str(info),APPLICATION_EXTENSION_API_ONLY='YES',SWIFT_OPTIMIZATION_LEVEL='-O',SKIP_INSTALL='YES',SUPPORTED_PLATFORMS='macosx',CODE_SIGN_ENTITLEMENTS=str(R/'Widget/Widget.entitlements'))
config=add('config','XCBuildConfiguration',buildSettings=settings,name='Release');configs=add('configs','XCConfigurationList',buildConfigurations=[config],defaultConfigurationIsVisible=0,defaultConfigurationName='Release')
target=add('target','PBXNativeTarget',buildConfigurationList=configs,buildPhases=[sources,frameworks],buildRules=[],dependencies=[],name='CyanGitHubWidgets',productName='CyanGitHubWidgets',productReference=product,productType='com.apple.product-type.app-extension')
proj=add('project','PBXProject',attributes={'LastUpgradeCheck':'2700'},buildConfigurationList=configs,compatibilityVersion='Xcode 14.0',developmentRegion='en',knownRegions=['en','Base'],mainGroup=group,projectDirPath='',projectRoot='',targets=[target])
def s(v):
 if isinstance(v,dict):return '{'+''.join(json.dumps(k)+' = '+s(x)+';' for k,x in v.items())+'}'
 if isinstance(v,list):return '('+','.join(s(x) for x in v)+')'
 return str(v) if isinstance(v,int) else json.dumps(v)
(P/'project.pbxproj').write_text('// !$*UTF8*$!\n'+s(dict(archiveVersion=1,classes={},objectVersion=56,objects=o,rootObject=proj)))
