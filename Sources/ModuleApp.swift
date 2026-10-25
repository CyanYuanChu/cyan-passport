import SwiftUI
import AppKit

struct PluginContentView: NSViewControllerRepresentable {
    let plugin: GroveFeaturePlugin
    func makeNSViewController(context: Context) -> NSViewController { plugin.contentController }
    func updateNSViewController(_ controller: NSViewController, context: Context) {}
}
enum ShellMetadata {
    static let value = (try! JSONSerialization.jsonObject(with: Data(contentsOf: Bundle.main.url(forResource: "module", withExtension: "json")!))) as! [String:Any]
    static var id: String { value["id"] as! String }
    static var name: String { value["name"] as! String }
    static var pluginURL: URL { Bundle.main.bundleURL.appendingPathComponent("Contents/PlugIns/" + (value["moduleName"] as! String)) }
}

@MainActor final class ModuleDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let server = ModuleServer(); let startup = StartupManager()
    var handle: GrovePluginHandle?; var window: NSWindow?; var item: NSStatusItem?; var timer: Timer?
    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            guard try server.start(id: ShellMetadata.id, handler: { [weak self] action in await self?.respond(action) ?? [:] }) else {
                let id = ShellMetadata.id
                Task.detached { _ = try? ModuleIPC.request(id, action: "show"); await MainActor.run { NSApp.terminate(nil) } }; return
            }
            let handle = try GrovePluginHandle(url: ShellMetadata.pluginURL)
            if let error = handle.plugin.startFeature() { throw PluginError.message(error as String) }
            self.handle = handle; configureMenu()
            timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in Task { @MainActor in self?.updateItem() } }
            if !CommandLine.arguments.contains("--integrated") && !GroveLaunchContext.shouldStartQuietly(arguments: CommandLine.arguments, event: NSAppleEventManager.shared().currentAppleEvent) { show() }
            else { NSApp.setActivationPolicy(.accessory) }
        } catch {
            fputs(error.localizedDescription + "\n", stderr)
            if !CommandLine.arguments.contains("--smoke") { let alert = NSAlert(); alert.messageText = error.localizedDescription; alert.runModal() }
            server.stop(); NSApp.terminate(nil)
        }
    }
    func configureMenu() {
        item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        let menu = NSMenu(); menu.addItem(withTitle: "打开 " + ShellMetadata.name, action: #selector(show), keyEquivalent: "")
        menu.addItem(withTitle: "登录后自动启动", action: #selector(toggleStartup), keyEquivalent: "").state = startup.isEnabled ? .on : .off
        menu.addItem(.separator()); menu.addItem(withTitle: "退出 " + ShellMetadata.name, action: #selector(quit), keyEquivalent: "q")
        for entry in menu.items { entry.target = self }; item?.menu = menu
        let main = NSMenu(); let app = NSMenuItem(); app.submenu = menu; main.addItem(app)
        let edit = NSMenuItem(); let editMenu = NSMenu(title: "编辑")
        for (label, selector, key) in [("剪切", "cut:", "x"), ("复制", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] { editMenu.addItem(withTitle: label, action: Selector(selector), keyEquivalent: key) }
        edit.submenu = editMenu; main.addItem(edit); NSApp.mainMenu = main; updateItem()
    }
    func updateItem() {
        item?.button?.image = NSImage(systemSymbolName: ShellMetadata.value["icon"] as? String ?? "leaf", accessibilityDescription: ShellMetadata.name)
        let values = handle?.plugin.summary as? [String:String] ?? [:]
        item?.button?.toolTip = values.sorted { $0.key < $1.key }.map { $0.key + " " + $0.value }.joined(separator: "\n")
        if ShellMetadata.id == "cyan-monitor" { item?.button?.title = " " + ["CPU", "内存", "下载", "上传"].compactMap { key in values[key].map { key + " " + $0 } }.joined(separator: "  ") }
    }
    @objc func show() {
        guard let plugin = handle?.plugin else { return }
        if window == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 850), styleMask: [.titled,.closable,.miniaturizable,.resizable], backing: .buffered, defer: false)
            w.title = ShellMetadata.name
            w.contentViewController = plugin.contentController
            w.center(); w.isReleasedWhenClosed = false; w.delegate = self; window = w
        }
        NSApp.setActivationPolicy(.regular); NSApp.activate(ignoringOtherApps: true); window?.makeKeyAndOrderFront(nil)
    }
    @objc func toggleStartup() { Task { await startup.setEnabled(!startup.isEnabled); configureMenu() } }
    @objc func quit() { NSApp.terminate(nil) }
    func respond(_ action: String) async -> [String:Any] {
        let known = ["status","show","refresh","quit","panel","start","stop"]
        if action == "show" { show() }
        if action == "refresh" { handle?.plugin.refreshFeature() }
        if ["panel","start","stop"].contains(action) { handle?.plugin.performAction(action as NSString) }
        if action == "quit" { DispatchQueue.main.asyncAfter(deadline: .now()+0.15) { NSApp.terminate(nil) } }
        return ["protocolVersion":1,"featureAPI":2,"id":ShellMetadata.id,"version":ShellMetadata.value["version"]!,"ok":known.contains(action),"pid":ProcessInfo.processInfo.processIdentifier,"summary":handle?.plugin.summary ?? [:],"error":known.contains(action) ? "":"不支持的独立版动作"]
    }
    func applicationWillTerminate(_ notification: Notification) { timer?.invalidate(); handle?.plugin.stopFeature(); server.stop() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool { show(); return true }
    func application(_ application: NSApplication, open urls: [URL]) { show() }
}

@main struct StandaloneModule {
    @MainActor static func main() async {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--request"), args.count > i+1 {
            do { let value = try ModuleIPC.request(ShellMetadata.id, action: args[i+1]); print(String(data: try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]), encoding: .utf8)!) } catch { print(error.localizedDescription); exit(1) }; return
        }
        if args.contains("--probe-feature-lock") {
            do { let handle = try GrovePluginHandle(url: ShellMetadata.pluginURL); if let message = handle.plugin.startFeature() { print(message); exit(2) }; handle.plugin.stopFeature(); print("FEATURE_LEASE_FREE") } catch { print(error.localizedDescription); exit(1) }; return
        }
        if args.contains("--self-test") {
            do {
                let handle = try GrovePluginHandle(url: ShellMetadata.pluginURL)
                let success = await withCheckedContinuation { continuation in handle.plugin.runSelfTests { continuation.resume(returning: $0) } }
                if !success { exit(1) }
            } catch { print(error.localizedDescription); exit(1) }; return
        }
        let app = NSApplication.shared; let delegate = ModuleDelegate(); app.delegate = delegate
        withExtendedLifetime(delegate) { app.run() }
    }
}
