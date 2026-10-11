#!/usr/bin/env python3
"""Generate a dependency-free Xcode project referencing the production SwiftUI source files."""
import hashlib
from pathlib import Path

root = Path(__file__).resolve().parent
project = root / "DeepdeskUITests.xcodeproj"
project.mkdir(exist_ok=True)

def ident(name):
    return hashlib.sha256(name.encode()).hexdigest()[:24].upper()

def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"') + '"'

objects = []
def obj(name, value):
    objects.append(f"\t\t{ident(name)} = {{ {value} }};")
    return ident(name)

host_sources = [p for p in sorted((root.parent / "Sources/Deepdesk").glob("*.swift")) if p.name != "DeepdeskApp.swift"]
host_sources.append(root / "UITestHost.swift")
source_refs, source_builds = [], []
for file in host_sources:
    path = "../Sources/Deepdesk/" + file.name if file.parent.name == "Deepdesk" else file.name
    ref = obj("file:" + path, f"isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = {quoted(path)}; sourceTree = SOURCE_ROOT;")
    build = obj("build:" + path, f"isa = PBXBuildFile; fileRef = {ref};")
    source_refs.append(ref); source_builds.append(build)

test_ref = obj("testFile", 'isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = DeepdeskUITests.swift; sourceTree = SOURCE_ROOT;')
test_build = obj("testBuild", f"isa = PBXBuildFile; fileRef = {test_ref};")
resource_ref = obj("catalog", 'isa = PBXFileReference; lastKnownFileType = text.json; path = "../Sources/Deepdesk/Resources/model-catalog.json"; sourceTree = SOURCE_ROOT;')
resource_build = obj("catalogBuild", f"isa = PBXBuildFile; fileRef = {resource_ref};")
host_product = obj("hostProduct", 'isa = PBXFileReference; explicitFileType = wrapper.application; path = DeepdeskUITestHost.app; sourceTree = BUILT_PRODUCTS_DIR;')
test_product = obj("testProduct", 'isa = PBXFileReference; explicitFileType = wrapper.cfbundle; path = DeepdeskUITests.xctest; sourceTree = BUILT_PRODUCTS_DIR;')
package = obj("package", 'isa = XCLocalSwiftPackageReference; relativePath = ..;')
product = obj("coreProduct", f"isa = XCSwiftPackageProductDependency; package = {package}; productName = DeepdeskCore;")
framework = obj("coreBuild", f"isa = PBXBuildFile; productRef = {product};")
host_sources_phase = obj("hostSources", f"isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ({','.join(source_builds)},); runOnlyForDeploymentPostprocessing = 0;")
host_resource_phase = obj("hostResources", f"isa = PBXResourcesBuildPhase; buildActionMask = 2147483647; files = ({resource_build},); runOnlyForDeploymentPostprocessing = 0;")
host_framework_phase = obj("hostFrameworks", f"isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = ({framework},); runOnlyForDeploymentPostprocessing = 0;")
test_sources_phase = obj("testSources", f"isa = PBXSourcesBuildPhase; buildActionMask = 2147483647; files = ({test_build},); runOnlyForDeploymentPostprocessing = 0;")
test_framework_phase = obj("testFrameworks", "isa = PBXFrameworksBuildPhase; buildActionMask = 2147483647; files = (); runOnlyForDeploymentPostprocessing = 0;")
proxy = obj("proxy", f"isa = PBXContainerItemProxy; containerPortal = {ident('project')}; proxyType = 1; remoteGlobalIDString = {ident('hostTarget')}; remoteInfo = DeepdeskUITestHost;")
dependency = obj("dependency", f"isa = PBXTargetDependency; target = {ident('hostTarget')}; targetProxy = {proxy};")
products_group = obj("products", f"isa = PBXGroup; children = ({host_product},{test_product},); name = Products; sourceTree = \"<group>\";")
main_group = obj("mainGroup", f"isa = PBXGroup; children = ({','.join(source_refs)},{test_ref},{resource_ref},{products_group},); sourceTree = \"<group>\";")

common = 'SDKROOT = macosx; MACOSX_DEPLOYMENT_TARGET = 26.4; SWIFT_VERSION = 6.0; ARCHS = arm64; ONLY_ACTIVE_ARCH = YES; CLANG_ENABLE_MODULES = YES;'
for scope in ["project", "host", "test"]:
    settings = common
    if scope == "host":
        settings += ' PRODUCT_NAME = DeepdeskUITestHost; PRODUCT_BUNDLE_IDENTIFIER = dev.emin.DeepdeskUITestHost; GENERATE_INFOPLIST_FILE = YES; INFOPLIST_KEY_NSPrincipalClass = NSApplication; CODE_SIGN_IDENTITY = "-"; CODE_SIGN_ENTITLEMENTS = UIHost.entitlements; ENABLE_APP_SANDBOX = YES;'
    if scope == "test":
        settings += ' PRODUCT_NAME = DeepdeskUITests; PRODUCT_BUNDLE_IDENTIFIER = dev.emin.DeepdeskUITests; GENERATE_INFOPLIST_FILE = YES; TEST_TARGET_NAME = DeepdeskUITestHost; CODE_SIGN_IDENTITY = "-";'
    configs=[]
    for mode in ["Debug", "Release"]:
        config = obj(scope+mode, f"isa = XCBuildConfiguration; buildSettings = {{ {settings} SWIFT_OPTIMIZATION_LEVEL = {quoted('-Onone' if mode == 'Debug' else '-O')}; }}; name = {mode};")
        configs.append(config)
    obj(scope+"Configs", f"isa = XCConfigurationList; buildConfigurations = ({','.join(configs)},); defaultConfigurationIsVisible = 0; defaultConfigurationName = Debug;")
obj("hostTarget", f"isa = PBXNativeTarget; buildConfigurationList = {ident('hostConfigs')}; buildPhases = ({host_sources_phase},{host_framework_phase},{host_resource_phase},); buildRules = (); dependencies = (); name = DeepdeskUITestHost; packageProductDependencies = ({product},); productName = DeepdeskUITestHost; productReference = {host_product}; productType = \"com.apple.product-type.application\";")
obj("testTarget", f"isa = PBXNativeTarget; buildConfigurationList = {ident('testConfigs')}; buildPhases = ({test_sources_phase},{test_framework_phase},); buildRules = (); dependencies = ({dependency},); name = DeepdeskUITests; productName = DeepdeskUITests; productReference = {test_product}; productType = \"com.apple.product-type.bundle.ui-testing\";")
obj("project", f"isa = PBXProject; attributes = {{ LastUpgradeCheck = 2660; TargetAttributes = {{ {ident('testTarget')} = {{ TestTargetID = {ident('hostTarget')}; }}; }}; }}; buildConfigurationList = {ident('projectConfigs')}; compatibilityVersion = \"Xcode 14.0\"; developmentRegion = en; hasScannedForEncodings = 0; knownRegions = (en,Base); mainGroup = {main_group}; packageReferences = ({package},); productRefGroup = {products_group}; projectDirPath = \"\"; projectRoot = \"\"; targets = ({ident('hostTarget')},{ident('testTarget')},);")
(project / "project.pbxproj").write_text('// !$*UTF8*$!\n{\n\tarchiveVersion = 1;\n\tclasses = {};\n\tobjectVersion = 56;\n\tobjects = {\n' + '\n'.join(objects) + '\n\t};\n\trootObject = '+ident('project')+';\n}\n')
schemes = project / "xcshareddata/xcschemes"
schemes.mkdir(parents=True, exist_ok=True)
ref = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{ident("hostTarget")}" BuildableName="DeepdeskUITestHost.app" BlueprintName="DeepdeskUITestHost" ReferencedContainer="container:DeepdeskUITests.xcodeproj"/>'
testref = f'<BuildableReference BuildableIdentifier="primary" BlueprintIdentifier="{ident("testTarget")}" BuildableName="DeepdeskUITests.xctest" BlueprintName="DeepdeskUITests" ReferencedContainer="container:DeepdeskUITests.xcodeproj"/>'
(schemes / "DeepdeskUITestHost.xcscheme").write_text(f'''<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion="2660" version="1.3"><BuildAction parallelizeBuildables="YES" buildImplicitDependencies="YES"><BuildActionEntries><BuildActionEntry buildForTesting="YES" buildForRunning="YES" buildForProfiling="NO" buildForArchiving="NO" buildForAnalyzing="YES">{ref}</BuildActionEntry></BuildActionEntries></BuildAction><TestAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv="YES"><Testables><TestableReference skipped="NO">{testref}</TestableReference></Testables></TestAction><LaunchAction buildConfiguration="Debug" selectedDebuggerIdentifier="Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier="Xcode.IDEFoundation.Launcher.LLDB" launchStyle="0" useCustomWorkingDirectory="NO" ignoresPersistentStateOnLaunch="YES" debugDocumentVersioning="YES" allowLocationSimulation="NO"><BuildableProductRunnable runnableDebuggingMode="0">{ref}</BuildableProductRunnable></LaunchAction><AnalyzeAction buildConfiguration="Debug"/><ArchiveAction buildConfiguration="Release" revealArchiveInOrganizer="NO"/></Scheme>''')
print(project)
