import AppKit
import SwiftUI
import Darwin

// CyanPassportFeatureV2 在构建前按模块生成，Objective-C 类名在所有模块之间唯一。
@MainActor @objc(CyanPassportFeatureV2) final class PluginEntry: NSObject, GroveFeaturePlugin {
    private var feature: FeatureController?
    private var controller: NSViewController?
    private var lease: Int32 = -1
    private var active = false
    var moduleInfo: NSDictionary { ModuleMetadata.value as NSDictionary }
    var contentController: NSViewController {
        if let controller { return controller }
        if feature == nil { feature = FeatureController() }
        let content = feature!.content
        let view: AnyView
        if ModuleMetadata.id == "cyan-github" { view = content }
        else { view = AnyView(ScrollView { content.padding(28).frame(maxWidth: .infinity, alignment: .topLeading) }.background(GrovePalette().background)) }
        let controller = NSHostingController(rootView: view)
        self.controller = controller; return controller
    }
    var summary: NSDictionary { (feature?.summary ?? [:]) as NSDictionary }
    func startFeature() -> NSString? {
        if active { return nil }
        do {
            try ModuleIPC.prepare()
            let path = ModuleIPC.socketPath(ModuleMetadata.id) + ".feature-lock"
            let fd = open(path, O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
            guard fd >= 0 else { throw PluginError.message("无法锁定功能模块") }
            guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { close(fd); throw PluginError.message("这个功能正在另一个 Grove 或独立版中使用，请先停用另一处。") }
            lease = fd
            ModuleMigration.run(id: ModuleMetadata.id)
            if feature == nil { feature = FeatureController() }
            feature!.start(); active = true; return nil
        } catch { return error.localizedDescription as NSString }
    }
    func stopFeature() {
        guard active else { return }; feature?.stop(); active = false; controller = nil; feature = nil
        if lease >= 0 { flock(lease, LOCK_UN); close(lease); lease = -1 }
    }
    func refreshFeature() { if active { feature?.refresh() } }
    func performAction(_ action: NSString) { if active { Task { await feature?.perform(action as String) } } }
    func runSelfTests(_ completion: @escaping (Bool) -> Void) { Task { await FeatureChecks.run(); completion(true) } }
}

@_cdecl("cyan_grove_feature_create_v2") public func createGroveFeature() -> UnsafeMutableRawPointer {
    let pointer = MainActor.assumeIsolated { UInt(bitPattern: Unmanaged.passRetained(PluginEntry()).toOpaque()) }
    return UnsafeMutableRawPointer(bitPattern: pointer)!
}

enum FeatureResources {
    static let bundle = Bundle(for: PluginEntry.self)
}
enum ModuleMetadata {
    static let value: [String:Any] = {
        let url = FeatureResources.bundle.url(forResource: "module", withExtension: "json")!
        return (try? JSONSerialization.jsonObject(with: Data(contentsOf: url))) as? [String:Any] ?? [:]
    }()
    static var id: String { value["id"] as! String }
}
enum FeaturePreferences {
    static let shared = UserDefaults(suiteName: (ModuleMetadata.value["bundleID"] as! String) + ".shared")!
}
