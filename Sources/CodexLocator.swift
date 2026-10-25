import Foundation
enum CodexRPC {
    static var executable: String? {
        let env=ProcessInfo.processInfo.environment
        var candidates=[env["CODEX_BIN"],"/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex","/Applications/Codex.app/Contents/Resources/codex",NSHomeDirectory()+"/.local/bin/codex","/opt/homebrew/bin/codex","/usr/local/bin/codex"].compactMap{$0}
        candidates += (env["PATH"] ?? "").split(separator:":").map{String($0)+"/codex"}
        return candidates.first{ FileManager.default.isExecutableFile(atPath:$0) }
    }
}
