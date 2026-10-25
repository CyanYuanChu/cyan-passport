import Foundation
import AppKit
@MainActor enum FeatureChecks {
    static func run() async {
        var failed = 0
        func check(_ condition: Bool, _ name: String) { print((condition ? "PASS " : "FAIL ") + name); if !condition { failed += 1 } }
        check(ModuleMetadata.value["protocolVersion"] as? Int == 2, "module protocol metadata")
        check(!ModuleMetadata.id.contains("/"), "stable module identity")
        check(FileManager.default.fileExists(atPath: FeatureResources.bundle.resourcePath! + "/module.json"), "standalone manifest bundled")
        var c = PassportConfiguration(); c.workspace = FileManager.default.temporaryDirectory.path; c.pythonPath = "/usr/bin/python3"
        check(c.permissionMode == "workspace", "public default keeps workspace permissions")
        check((try? c.validate()) != nil, "valid bridge configuration")
        c.port = 80; check((try? c.validate()) == nil, "invalid bridge port rejected")
        check(PassportBridgeStore.directory.lastPathComponent == "CyanPassport", "independent bridge data")
        let names = (try? FileManager.default.contentsOfDirectory(atPath: FeatureResources.bundle.resourcePath! + "/PassportBridge")) ?? []
        check(names.contains("bridge.py") && !names.contains("token") && !names.contains("local"), "bridge includes code without pairing secrets")
        print("MODULE_TESTS \(failed == 0 ? "OK" : "FAILED")")
        if failed > 0 { exit(1) }
    }
}
