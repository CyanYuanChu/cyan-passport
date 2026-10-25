import AppKit
import ServiceManagement
import SwiftUI
import CoreServices

@MainActor final class StartupManager: ObservableObject {
    @Published private(set) var status = SMAppService.mainApp.status
    @Published private(set) var busy = false
    @Published private(set) var error: String?

    var isEnabled: Bool { status == .enabled || status == .requiresApproval }
    var needsApproval: Bool { status == .requiresApproval }
    var statusName: String {
        switch status {
        case .enabled: return "enabled"
        case .requiresApproval: return "requiresApproval"
        case .notRegistered: return "notRegistered"
        case .notFound: return "notFound"
        @unknown default: return "unknown"
        }
    }
    var detail: String {
        switch status {
        case .enabled: return "已开启 · 登录 Mac 后自动恢复菜单栏，不弹出工作台。"
        case .requiresApproval: return "已添加登录项，需在系统设置中允许 Cyan Passport。"
        case .notRegistered: return "开启后，登录 Mac 时自动显示菜单栏信息。"
        case .notFound: return "请把 Cyan Passport 放入应用程序目录后重新开启。"
        @unknown default: return "暂时无法确认系统登录项状态。"
        }
    }
    func refresh() { status = SMAppService.mainApp.status }

    func setEnabled(_ enabled: Bool) async {
        guard !busy else { return }
        refresh()
        if enabled == isEnabled { error = nil; return }
        // Avoid registering an ephemeral Xcode build as the user's login item.
        let path = Bundle.main.bundleURL.standardizedFileURL.path
        guard path.hasPrefix("/Applications/") || path.hasPrefix(NSHomeDirectory() + "/Applications/") else {
            error = "请先将 Cyan Passport 放入应用程序目录，再配置自动启动。"
            return
        }
        busy = true; error = nil
        defer { busy = false; refresh() }
        do {
            if enabled { try SMAppService.mainApp.register() }
            else { try await SMAppService.mainApp.unregister() }
        } catch {
            refresh()
            // System Settings can change status while a request is in progress.
            if status != .requiresApproval && enabled != isEnabled {
                self.error = "自动启动设置未完成，请在系统设置 → 通用 → 登录项中检查。"
            }
        }
    }
    func openSystemSettings() { SMAppService.openSystemSettingsLoginItems() }
}

enum GroveLaunchContext {
    static func shouldStartQuietly(arguments: [String], event: NSAppleEventDescriptor?) -> Bool {
        if arguments.contains("--background") { return true }
        guard let event, event.eventClass == AEEventClass(kCoreEventClass),
              event.eventID == AEEventID(kAEOpenApplication) else { return false }
        let reason = event.paramDescriptor(forKeyword: AEKeyword(keyAEPropData))?.enumCodeValue
        return reason == OSType(keyAELaunchedAsLogInItem) || reason == OSType(keyAELaunchedAsServiceItem)
    }
}

struct StartupSettingsView: View {
    @ObservedObject var manager: StartupManager
    var p: GrovePalette
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("登录后自动启动", systemImage: "power").font(.system(size: 14, weight: .semibold))
                Spacer()
                Toggle("登录后自动启动", isOn: Binding(
                    get: { manager.isEnabled },
                    set: { enabled in Task { await manager.setEnabled(enabled) } }
                )).labelsHidden().toggleStyle(.switch).tint(p.accent).disabled(manager.busy)
            }
            Text(manager.detail).font(.system(size: 11)).foregroundStyle(p.secondary)
            if let error = manager.error { Text(error).font(.system(size: 11)).foregroundStyle(.orange) }
            if manager.needsApproval {
                Button("打开系统登录项设置") { manager.openSystemSettings() }
                    .font(.system(size: 11))
            }
        }
        .padding(22).frame(maxWidth: .infinity, alignment: .leading)
        .background(p.card, in: RoundedRectangle(cornerRadius: 18))
        .onAppear { manager.refresh() }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in manager.refresh() }
    }
}
