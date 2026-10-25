import Foundation
extension PassportBridgeStore {
    func prepareRuntime() async {
        guard !busy, let script = FeatureResources.bundle.url(forResource: "setup-runtime", withExtension: "sh") else { return }
        busy = true; defer { busy = false }
        do {
            let resources = FeatureResources.bundle.resourceURL!.appendingPathComponent("PassportBridge/requirements.txt").path
            let text = try await Task.detached { try Self.setupOutput(script: script.path, requirements: resources) }.value
            configuration.pythonPath = Self.directory.appendingPathComponent("venv/bin/python").path
            notice = "运行环境已准备好。" + String(text.suffix(100)); error = nil
        } catch { self.error = error.localizedDescription }
    }
    nonisolated static func setupOutput(script: String, requirements: String) throws -> String {
        let p = Process(); p.executableURL = URL(fileURLWithPath: "/bin/zsh"); p.arguments = [script, requirements]
        let output = Pipe(); p.standardOutput = output; p.standardError = output
        try p.run(); let data = output.fileHandleForReading.readDataToEndOfFile(); p.waitUntilExit()
        guard p.terminationStatus == 0 else { throw GroveError.message("运行环境准备失败：" + String((String(data: data, encoding: .utf8) ?? "").suffix(1800))) }
        return String(data: data, encoding: .utf8) ?? ""
    }
}
