import Foundation
import AppKit
import Darwin
import Security

struct PassportConfiguration: Codable, Equatable {
    var workspace = NSHomeDirectory()
    var listenHost = "auto"
    var port = 9443
    var taskModel = "gpt-6.1-sol"
    var voiceModel = ""
    var permissionMode = "workspace"
    var keepAwake = true
    var autoStart = false
    var pythonPath = NSHomeDirectory() + "/Library/Application Support/CyanPassport/venv/bin/python"
    var backend: String? = "codex"
    var hermesURL: String? = "http://127.0.0.1:8642"
    var backendChoice: String { get { backend ?? "codex" } set { backend = newValue } }
    var gatewayURL: String { get { hermesURL ?? "http://127.0.0.1:8642" } set { hermesURL = newValue } }
    func validate() throws {
        guard ["codex","hermes"].contains(backendChoice) else { throw GroveError.message("后端选择无效。") }
        guard let endpoint = URLComponents(string: gatewayURL), let host = endpoint.host, endpoint.user == nil, endpoint.password == nil, endpoint.query == nil, endpoint.fragment == nil, endpoint.scheme == "https" || (endpoint.scheme == "http" && ["127.0.0.1","localhost","::1"].contains(host)) else { throw GroveError.message("Hermes 地址需使用 HTTPS 或本机回环 HTTP。") }
        if backendChoice == "hermes" && permissionMode != "bypass" { throw GroveError.message("当前 Hermes 语音适配器仅支持已明确授权的 Bypass 配置。") }
        guard (1024...65535).contains(port) else { throw GroveError.message("端口需在 1024–65535 之间。") }
        var directory: ObjCBool = false
        guard workspace.hasPrefix("/"), FileManager.default.fileExists(atPath: workspace, isDirectory: &directory), directory.boolValue else { throw GroveError.message("请选择存在的工作目录。") }
        guard ["readonly", "workspace", "bypass"].contains(permissionMode) else { throw GroveError.message("权限配置无效。") }
        guard !listenHost.isEmpty, !listenHost.contains(where: { $0.isWhitespace }) else { throw GroveError.message("监听地址无效。") }
        for model in [taskModel, voiceModel] where !model.isEmpty {
            guard model.range(of: "^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$", options: .regularExpression) != nil else { throw GroveError.message("模型标识中包含不支持的字符。") }
        }
        guard pythonPath.hasPrefix("/"), FileManager.default.isExecutableFile(atPath: pythonPath) else { throw GroveError.message("Python 运行环境不可用，请检查高级设置。") }
    }
}
struct PassportRuntime: Codable {
    var pid: Int32
    var managedBy: String
    var startedAt: Double
    var updatedAt: Double
    var state: String
    var deviceConnected: Bool
    var listenHost: String
    var port: Int
    var permissionMode: String
    var taskModel: String
    var voiceModel: String
    var threadId: String?
    var error: String?
    var discoveryState: String?
    var backend: String?
    var title: String {
        switch state { case "active": return "正在通话"; case "dialing": return "正在接通"; case "idle": return "设备已就绪"; case "error": return "通话异常"; default: return "等待设备连接" }
    }
    var fresh: Bool { Date().timeIntervalSince1970 - updatedAt < 12 && state != "stopped" && kill(pid, 0) == 0 }
}
struct PassportModel: Decodable, Identifiable { var id: String; var name: String }
struct PassportModelResponse: Decodable { var models: [PassportModel] }

@MainActor final class PassportBridgeStore: ObservableObject {
    static let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("CyanPassport", isDirectory: true)
    static let configurationURL = directory.appendingPathComponent("settings.json")
    static let statusURL = directory.appendingPathComponent("status.json")
    static let logURL = directory.appendingPathComponent("bridge.log")
    @Published var configuration = PassportConfiguration()
    @Published var runtime: PassportRuntime?
    @Published var running = false
    @Published var busy = false
    @Published var error: String?
    @Published var notice: String?
    @Published var logExcerpt = "尚无运行事件"
    @Published var models = [PassportModel(id: "gpt-6.1-sol", name: "GPT-6.1 Sol"), PassportModel(id: "gpt-6-astra", name: "GPT-6 Astra"), PassportModel(id: "gpt-6-luna", name: "GPT-6 Luna")]
    @Published var modelLoading = false
    @Published var pairingCode = ""
    @Published var pairingExpires: Date?
    private var process: Process?
    private var logHandle: FileHandle?
    private var timer: Timer?
    private var activity: NSObjectProtocol?
    var configured: Bool { ["server.pem", "server-key.pem", "token"].allSatisfy { FileManager.default.fileExists(atPath: Self.directory.appendingPathComponent($0).path) } }
    var resourceDirectory: URL? { FeatureResources.bundle.url(forResource: "PassportBridge", withExtension: nil) }
    var dirty: Bool { guard let data = try? Data(contentsOf: Self.configurationURL), let saved = try? JSONDecoder().decode(PassportConfiguration.self, from: data) else { return true }; return saved != configuration }
    init() { if let data = try? Data(contentsOf: Self.configurationURL), let saved = try? JSONDecoder().decode(PassportConfiguration.self, from: data) { configuration = saved } }
    func begin() {
        do { try migratePairing() } catch { self.error = error.localizedDescription }
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in Task { @MainActor in self?.refresh() } }
        if configuration.autoStart && !CommandLine.arguments.contains("--no-autostart") { Task { await start() } }
    }
    private func prepareDirectory() throws {
        try FileManager.default.createDirectory(at: Self.directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: Self.directory.path)
    }
    private func migratePairing() throws {
        try prepareDirectory()
        let legacy = URL(fileURLWithPath: NSHomeDirectory() + "/Library/Application Support/CyanGrove/Passport", isDirectory: true)
        for name in ["server.pem", "server-key.pem", "token", "target-thread.json"] {
            let source = legacy.appendingPathComponent(name), destination = Self.directory.appendingPathComponent(name)
            if !FileManager.default.fileExists(atPath: destination.path), FileManager.default.fileExists(atPath: source.path) {
                try FileManager.default.copyItem(at: source, to: destination)
                try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
            }
        }
    }
    func save() -> Bool {
        do {
            try configuration.validate(); try prepareDirectory()
            let data = try JSONEncoder().encode(configuration)
            try data.write(to: Self.configurationURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: Self.configurationURL.path)
            notice = running ? "配置已保存，重启桥接后生效。" : "配置已保存。"; error = nil
            updateAwake(); return true
        } catch { self.error = error.localizedDescription; return false }
    }
    func refresh() {
        let window = Self.directory.appendingPathComponent("pairing-window.json")
        if let data = try? Data(contentsOf: window), let value = try? JSONSerialization.jsonObject(with: data) as? [String:Any], let code = value["code"] as? String, let expires = value["expiresAt"] as? Double, expires > Date().timeIntervalSince1970 {
            pairingCode = stride(from: 0, to: code.count, by: 4).map { index in String(code.dropFirst(index).prefix(4)) }.joined(separator: "-")
            pairingExpires = Date(timeIntervalSince1970: expires)
        } else { pairingCode = ""; pairingExpires = nil }
        if let data = try? Data(contentsOf: Self.statusURL), let value = try? JSONDecoder().decode(PassportRuntime.self, from: data), value.managedBy == "cyan-passport" {
            runtime = value; running = value.fresh
        } else { runtime = nil; running = process?.isRunning == true }
        if let handle = try? FileHandle(forReadingFrom: Self.logURL) {
            defer { try? handle.close() }
            if let end = try? handle.seekToEnd() { try? handle.seek(toOffset: end > 8000 ? end - 8000 : 0) }
            if let data = try? handle.readToEnd(), let text = String(data: data, encoding: .utf8) {
                logExcerpt = text.split(separator: "\n").suffix(12).joined(separator: "\n")
            }
        }
        updateAwake()
    }
    private func updateAwake() {
        if configuration.keepAwake && running && activity == nil { activity = ProcessInfo.processInfo.beginActivity(options: [.idleSystemSleepDisabled], reason: "AI Passport 局域网语音桥") }
        if (!configuration.keepAwake || !running), let token = activity { ProcessInfo.processInfo.endActivity(token); activity = nil }
    }
    private var legacyBridgeRunning: Bool {
        let url = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("CyanGrove/Passport/status.json")
        guard let data = try? Data(contentsOf: url), let value = try? JSONSerialization.jsonObject(with: data) as? [String:Any],
              let pid = value["pid"] as? Int32, pid > 0, let updated = value["updatedAt"] as? Double,
              Date().timeIntervalSince1970 - updated < 12, value["state"] as? String != "stopped", value["managedBy"] as? String == "cyangrove" else { return false }
        return kill(pid, 0) == 0
    }
    func start() async {
        guard !legacyBridgeRunning else { error = "旧版语音桥仍在运行。请先结束并停止旧版通话，再在 Grove 中启动桥接。"; return }
        guard !busy else { return }; refresh(); guard !running else { return }
        guard save() else { return }
        guard let resources = resourceDirectory else { error = "应用内的桥接组件缺失，请重新安装当前构建。"; return }
        busy = true; error = nil; notice = nil
        defer { busy = false }
        do {
            let fm = FileManager.default
            if let size = (try? fm.attributesOfItem(atPath: Self.logURL.path)[.size]) as? NSNumber, size.intValue > 2_000_000 {
                let old = Self.directory.appendingPathComponent("bridge.previous.log"); try? fm.removeItem(at: old); try fm.moveItem(at: Self.logURL, to: old)
            }
            if !fm.fileExists(atPath: Self.logURL.path) { fm.createFile(atPath: Self.logURL.path, contents: Data(), attributes: [.posixPermissions: 0o600]) }
            let output = try FileHandle(forWritingTo: Self.logURL); try output.seekToEnd()
            let child = Process(); child.executableURL = URL(fileURLWithPath: configuration.pythonPath)
            child.arguments = ["-u", resources.appendingPathComponent("bridge.py").path, "serve", "--codex-new", "--config", Self.configurationURL.path, "--status-file", Self.statusURL.path, "--managed-by", "cyan-passport"]
            child.currentDirectoryURL = URL(fileURLWithPath: configuration.workspace)
            var environment = ProcessInfo.processInfo.environment
            environment["CYAN_PASSPORT_DATA_DIR"] = Self.directory.path
            environment["PATH"] = [NSHomeDirectory()+"/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"].joined(separator: ":")
            if let codex = CodexRPC.executable { environment["PATH"] = URL(fileURLWithPath: codex).deletingLastPathComponent().path + ":" + environment["PATH"]! }
            child.environment = environment; child.standardInput = FileHandle.nullDevice; child.standardOutput = output; child.standardError = output
            child.terminationHandler = { [weak self] stopped in Task { @MainActor in
                guard let self else { return }
                if self.process?.processIdentifier == stopped.processIdentifier {
                    self.process = nil; try? self.logHandle?.close(); self.logHandle = nil; self.refresh()
                    if stopped.terminationStatus != 0 && !self.busy { self.error = "桥接已退出，请查看最近事件。" }
                }
            } }
            try child.run(); process = child; logHandle = output; running = true
            try? await Task.sleep(nanoseconds: 800_000_000); refresh()
            if !child.isRunning { error = "启动失败，可能是端口已占用。请查看最近事件。" }
        } catch { self.error = error.localizedDescription; running = false }
    }
    private func managedPID() async -> Int32? {
        if let process, process.isRunning { return process.processIdentifier }
        guard let runtime, runtime.managedBy == "cyan-passport", runtime.fresh, let resources = resourceDirectory else { return nil }
        let expected = resources.appendingPathComponent("bridge.py").path, pid = runtime.pid
        let result = try? await Task.detached { try Self.output(executable: "/bin/ps", arguments: ["-p", String(pid), "-o", "command="]) }.value
        guard let command = result, command.contains(expected), command.contains("--managed-by cyan-passport") else { return nil }
        return pid
    }
    func stop() async {
        guard !busy else { return }; busy = true; defer { busy = false; refresh() }
        guard let pid = await managedPID() else { if running { error = "无法确认进程归属，没有停止其他程序。" }; return }
        kill(pid, SIGINT)
        for _ in 0..<80 { if kill(pid, 0) != 0 { break }; try? await Task.sleep(nanoseconds: 100_000_000) }
        if kill(pid, 0) == 0 { kill(pid, SIGTERM) }
        running = false; notice = "语音桥已停止。"
    }
    func restart() async { guard save() else { return }; if running { await stop() }; await start() }
    func allowPairing() async {
        if !running { await start() }
        guard running else { return }
        do {
            try prepareDirectory()
            let alphabet = Array("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
            var bytes = [UInt8](repeating: 0, count: 16)
            guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw GroveError.message("无法生成配对码。") }
            let code = String(bytes.map { alphabet[Int($0) & 31] })
            let data = try JSONSerialization.data(withJSONObject: ["code":code,"expiresAt":Date().timeIntervalSince1970+300])
            let url = Self.directory.appendingPathComponent("pairing-window.json")
            try data.write(to: url, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600], ofItemAtPath:url.path)
            notice = "配对窗口已打开，5 分钟内有效。请在设备配置网页输入配对码。"; refresh()
        } catch { self.error = error.localizedDescription }
    }
    func closePairing() {
        try? FileManager.default.removeItem(at: Self.directory.appendingPathComponent("pairing-window.json"))
        pairingCode = ""; pairingExpires = nil
    }
    func stopForQuit() {
        closePairing()
        timer?.invalidate()
        if let process, process.isRunning { process.interrupt() }
        if let activity { ProcessInfo.processInfo.endActivity(activity); self.activity = nil }
    }
    func chooseWorkspace() {
        let panel = NSOpenPanel(); panel.canChooseFiles = false; panel.canChooseDirectories = true; panel.canCreateDirectories = false; panel.prompt = "设为语音任务工作目录"
        if panel.runModal() == .OK, let url = panel.url { configuration.workspace = url.path }
    }
    func openDataDirectory() { NSWorkspace.shared.open(Self.directory) }
    func loadModels() async {
        guard !modelLoading, let resources = resourceDirectory else { return }; modelLoading = true
        defer { modelLoading = false }
        let executable = configuration.pythonPath, helper = resources.appendingPathComponent("manage.py").path
        do {
            let text = try await Task.detached { try Self.output(executable: executable, arguments: [helper, "models"]) }.value
            let response = try JSONDecoder().decode(PassportModelResponse.self, from: Data(text.utf8))
            if !response.models.isEmpty { models = response.models }
        } catch { self.error = "读取模型列表失败，保留已有选项。" }
    }
    nonisolated static func output(executable: String, arguments: [String]) throws -> String {
        let child = Process(); child.executableURL = URL(fileURLWithPath: executable); child.arguments = arguments
        let pipe = Pipe(); child.standardOutput = pipe; child.standardError = FileHandle.nullDevice
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = NSHomeDirectory()+"/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        child.environment = environment
        try child.run()
        let timeout = DispatchWorkItem { if child.isRunning { child.terminate() } }; DispatchQueue.global().asyncAfter(deadline: .now()+25, execute: timeout)
        defer { timeout.cancel() }
        let data = pipe.fileHandleForReading.readDataToEndOfFile(); child.waitUntilExit()
        guard child.terminationStatus == 0, data.count < 1_000_000 else { throw GroveError.message("本机运行组件没有成功返回。") }
        return String(data: data, encoding: .utf8) ?? ""
    }
}
