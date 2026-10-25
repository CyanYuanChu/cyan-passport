import Foundation

enum ModuleMigration {
    static func run(id: String) {
        let defaults = UserDefaults.standard
        guard !defaults.bool(forKey: "cyan.migration.v1") else { return }
        let legacy = UserDefaults(suiteName: "local.gitgrove.native")
        let keys: [String]
        switch id {
        case "cyan-command": keys = ["cyan.command.shortcut"]
        case "cyan-monitor": keys = ["cyan.menu.metrics"]
        case "cyan-github": keys = ["login","dark"]
        case "cyan-codex-usage": keys = ["cyan.codex.dailyPlan"]
        default: keys = []
        }
        for key in keys where defaults.object(forKey: key) == nil { if let value = legacy?.object(forKey: key) { defaults.set(value, forKey: key) } }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let pairs: [(String,String)]
        switch id {
        case "cyan-codex-usage": pairs = ["quota.json","quota-history.json","session-index-v2.json"].map { ("CyanGrove/"+$0,"CyanCodexUsage/"+$0) }
        case "cyan-passport": pairs = ["settings.json","server.pem","server-key.pem","token","target-thread.json","paired-devices.json"].map { ("CyanGrove/Passport/"+$0,"CyanPassport/"+$0) }
        default: pairs = []
        }
        do {
            for (a,b) in pairs {
                let src = support.appendingPathComponent(a), dst = support.appendingPathComponent(b)
                if FileManager.default.fileExists(atPath: src.path), !FileManager.default.fileExists(atPath: dst.path) {
                    try FileManager.default.createDirectory(at: dst.deletingLastPathComponent(), withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
                    try FileManager.default.copyItem(at: src, to: dst); try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: dst.path)
                }
            }
            defaults.set(true, forKey: "cyan.migration.v1")
        } catch { fputs("配置迁移尚未完成，将在下次启动重试。\n", stderr) }
    }
}
