import SwiftUI
import AppKit

@MainActor final class FeatureController: ObservableObject {
    let passport = PassportBridgeStore()
    var content: AnyView { AnyView(PassportPage(store: passport, p: GrovePalette())) }
    func start() { passport.begin() }
    func stop() { passport.stopForQuit() }
    func refresh() { passport.refresh() }
    func perform(_ action: String) async { if action == "start" { await passport.start() }; if action == "stop" { await passport.stop() } }
    var summary: [String:String] { ["语音桥": passport.running ? (passport.runtime?.title ?? "运行中") : "已停止", "设备": passport.runtime?.deviceConnected == true ? "已连接" : "未连接", "运行环境": FileManager.default.isExecutableFile(atPath: passport.configuration.pythonPath) ? "可用" : "请准备 Python 环境"] }
}

extension FeatureController { var menuImage: NSImage? { nil } }

extension FeatureController { var previewContent: AnyView { content } }
