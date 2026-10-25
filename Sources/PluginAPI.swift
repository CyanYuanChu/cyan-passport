import AppKit
import Foundation
import Darwin

// Objective-C 桥保持主程序与独立编译模块之间的接口稳定。
@MainActor @objc(CyanGroveFeatureV2) protocol GroveFeaturePlugin: NSObjectProtocol {
    var moduleInfo: NSDictionary { get }
    var contentController: NSViewController { get }
    var summary: NSDictionary { get }
    func startFeature() -> NSString?
    func stopFeature()
    func refreshFeature()
    func performAction(_ action: NSString)
    func runSelfTests(_ completion: @escaping (Bool) -> Void)
}

enum GrovePluginABI {
    static let version = 2
    typealias Factory = @convention(c) () -> UnsafeMutableRawPointer
}

@MainActor final class GrovePluginHandle {
    let plugin: GroveFeaturePlugin
    let url: URL
    // Swift 元数据可能被系统保留；代码随进程退出统一释放，不尝试 dlclose 热卸载。
    private let library: UnsafeMutableRawPointer
    init(url: URL) throws {
        self.url = url
        guard let bundle = Bundle(url: url), let executable = bundle.executableURL,
              executable.resolvingSymlinksInPath().path.hasPrefix(url.resolvingSymlinksInPath().path + "/") else { throw PluginError.message("功能包入口无效") }
        guard let library = dlopen(executable.path, RTLD_NOW | RTLD_LOCAL) else { throw PluginError.message(String(cString: dlerror())) }
        self.library = library
        guard let symbol = dlsym(library, "cyan_grove_feature_create_v2") else { throw PluginError.message("功能包缺少 Grove v2 入口") }
        let factory = unsafeBitCast(symbol, to: GrovePluginABI.Factory.self)
        let object = Unmanaged<AnyObject>.fromOpaque(factory()).takeRetainedValue()
        guard let plugin = object as? GroveFeaturePlugin else { throw PluginError.message("功能包接口不兼容") }
        self.plugin = plugin
    }
}

enum PluginError: LocalizedError {
    case message(String)
    var errorDescription: String? { if case let .message(text) = self { return text }; return nil }
}
