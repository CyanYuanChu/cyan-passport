import SwiftUI
import AppKit

@MainActor final class ModuleDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let feature = FeatureController(); let server = ModuleServer(); let startup = StartupManager()
    var window: NSWindow?; var item: NSStatusItem?; var timer: Timer?; var integrated = false; private var heartbeatCount = 0
    var metadata: [String:Any] { ModuleMetadata.value }
    var id: String { metadata["id"] as! String }; var name: String { metadata["name"] as! String }
    func applicationDidFinishLaunching(_ notification: Notification) {
        integrated = CommandLine.arguments.contains("--integrated")
        do {
            guard try server.start(id: id, handler: { [weak self] action in await self?.handle(action) ?? [:] }) else {
                let action = integrated ? "status" : "show"
                Task.detached { _ = try? ModuleIPC.request(ModuleMetadata.id, action: action); await MainActor.run { NSApp.terminate(nil) } }; return
            }
        } catch { let alert = NSAlert(); alert.messageText = error.localizedDescription; alert.runModal(); NSApp.terminate(nil); return }
        feature.start(); configureMenu()
        if !integrated && !GroveLaunchContext.shouldStartQuietly(arguments: CommandLine.arguments, event: NSAppleEventManager.shared().currentAppleEvent) { show() }
        else { NSApp.setActivationPolicy(.accessory) }
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in Task { @MainActor in self?.updateItem(); self?.checkHub() } }
        if CommandLine.arguments.contains("--smoke") {
            Task { try? await Task.sleep(nanoseconds: 3_000_000_000); print("MODULE_SMOKE_OK " + id); NSApp.terminate(nil) }
        }
    }
    func checkHub() {
        guard integrated else { return }; heartbeatCount += 1; guard heartbeatCount % 5 == 0 else { return }
        Task { let reachable = await Task.detached { (try? ModuleIPC.request("cyangrove", action: "status")) != nil }.value
            if !reachable && integrated { integrated = false; configureMenu() }
        }
    }
    func configureMenu() {
        if integrated { if let item { NSStatusBar.system.removeStatusItem(item) }; item = nil; return }
        if item == nil { item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength) }
        let menu = NSMenu(); menu.addItem(withTitle: "打开 " + name, action: #selector(show), keyEquivalent: "")
        if id == "cyan-command" { menu.addItem(withTitle: "打开快速指令", action: #selector(panel), keyEquivalent: "") }
        menu.addItem(.separator()); menu.addItem(withTitle: "退出 " + name, action: #selector(quit), keyEquivalent: "q")
        for entry in menu.items { entry.target = self }; item?.menu = menu; updateItem()
        let main = NSMenu(); let app = NSMenuItem(); let appMenu = NSMenu(); appMenu.addItem(withTitle: "退出 " + name, action: #selector(quit), keyEquivalent: "q").target = self; app.submenu = appMenu; main.addItem(app)
        let edit = NSMenuItem(); let editMenu = NSMenu(title: "编辑")
        for (label, selector, key) in [("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] { editMenu.addItem(withTitle: label, action: Selector(selector), keyEquivalent: key) }
        edit.submenu = editMenu; main.addItem(edit); NSApp.mainMenu = main
    }
    func updateItem() {
        item?.button?.image = feature.menuImage ?? NSImage(systemSymbolName: metadata["icon"] as? String ?? "leaf", accessibilityDescription: name)
        item?.button?.toolTip = feature.summary.sorted { $0.key < $1.key }.map { $0.key + " " + $0.value }.joined(separator: "\n")
    }
    @objc func show() {
        if window == nil {
            let root = VStack(spacing: 0) {
                HStack { GroveMark(size: 30); Text(name).font(.title2); Spacer() }.padding(22)
                ScrollView { VStack(alignment: .leading, spacing: 20) { feature.content; StartupSettingsView(manager: startup, p: GrovePalette()) }.padding(24) }
            }.frame(minWidth: id == "cyan-github" ? 1120 : 820, minHeight: 650).background(GrovePalette().background)
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: id == "cyan-github" ? 1180 : 980, height: 820), styleMask: [.titled,.closable,.miniaturizable,.resizable], backing: .buffered, defer: false)
            w.title = name; w.contentView = NSHostingView(rootView: root); w.center(); w.isReleasedWhenClosed = false; w.delegate = self; window = w
        }
        NSApp.setActivationPolicy(.regular); NSApp.activate(ignoringOtherApps: true); window?.makeKeyAndOrderFront(nil)
    }
    @objc func panel() { Task { await feature.perform("panel") } }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) { timer?.invalidate(); feature.stop(); server.stop() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { show(); return true }
    func application(_ application: NSApplication, open urls: [URL]) { show() }
    func handle(_ action: String) async -> [String:Any] {
        let known = ["status","show","refresh","quit","integrated","standalone","panel","start","stop"]
        var result: [String:Any] = ["protocolVersion": 1, "id": id, "version": metadata["version"]!, "ok": known.contains(action), "pid": ProcessInfo.processInfo.processIdentifier]
        if !known.contains(action) { result["error"] = "不支持的模块动作"; return result }
        switch action {
        case "show": show()
        case "refresh": feature.refresh()
        case "integrated": integrated = true; configureMenu()
        case "standalone": integrated = false; configureMenu()
        case "quit": DispatchQueue.main.asyncAfter(deadline: .now()+0.15) { NSApp.terminate(nil) }
        case "panel", "start", "stop": await feature.perform(action)
        default: break
        }
        result["summary"] = feature.summary; result["integrated"] = integrated; return result
    }
}

enum ModuleMetadata {
    static let value: [String:Any] = {
        guard let url = Bundle.main.url(forResource: "module", withExtension: "json"), let data = try? Data(contentsOf: url), let value = try? JSONSerialization.jsonObject(with: data) as? [String:Any] else { fatalError("Missing module.json") }; return value
    }()
    static var id: String { value["id"] as! String }
}

@main struct StandaloneModule {
    @MainActor static func main() async {
        ModuleMigration.run(id: ModuleMetadata.id)
        let args = CommandLine.arguments
        if args.contains("--self-test") { await FeatureChecks.run(); return }
        if let index = args.firstIndex(of: "--request"), args.count > index+1 {
            do { let value = try ModuleIPC.request(ModuleMetadata.id, action: args[index+1]); let data = try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]); print(String(data: data, encoding: .utf8)!)} catch { print(error.localizedDescription); exit(1) }; return
        }
        if let i = args.firstIndex(of: "--export-preview"), args.count > i+1 {
            _ = NSApplication.shared; let feature = FeatureController()
            let view = feature.previewContent.padding(28).frame(width: 1180, height: 900, alignment: .topLeading).background(GrovePalette().background)
            let renderer = ImageRenderer(content: view); renderer.scale = 1
            guard let image = renderer.nsImage, let tiff = image.tiffRepresentation, let bitmap = NSBitmapImageRep(data: tiff), let png = bitmap.representation(using: .png, properties: [:]) else { exit(1) }
            do { try png.write(to: URL(fileURLWithPath: args[i+1])); print("PREVIEW_OK") } catch { print(error); exit(1) }; return
        }
        let app = NSApplication.shared; let delegate = ModuleDelegate(); app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
