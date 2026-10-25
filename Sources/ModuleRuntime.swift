import Foundation
import AppKit
import Darwin

// 协议只接受明确列出的动作，socket 位于当前用户的私有目录。
enum ModuleIPC {
    static let version = 1
    static func directory(_ id: String) -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("CyanModules/" + id, isDirectory: true)
    }
    static func socketPath(_ id: String) -> String {
        // sockaddr_un 的路径长度有限；使用用户临时目录下的私有目录。
        let root = "/tmp/cyan-modules-\(getuid())"
        return root + "/" + id + ".sock"
    }
    static func prepare() throws {
        let root = "/tmp/cyan-modules-\(getuid())"
        if mkdir(root, 0o700) != 0 && errno != EEXIST { throw error("无法创建控制目录") }
        var st = stat()
        guard lstat(root, &st) == 0, st.st_uid == getuid(), st.st_mode & S_IFMT == S_IFDIR,
              st.st_mode & 0o077 == 0 else { throw error("控制目录权限不正确") }
    }
    static func error(_ text: String) -> NSError { NSError(domain: "CyanModules", code: 1, userInfo: [NSLocalizedDescriptionKey: text]) }
    static func address(_ path: String) throws -> sockaddr_un {
        guard path.utf8.count < 104 else { throw error("控制路径过长") }
        var address = sockaddr_un(); address.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &address.sun_path) { bytes in bytes.initializeMemory(as: UInt8.self, repeating: 0); bytes.copyBytes(from: path.utf8) }
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        return address
    }
    static func configure(_ fd: Int32) {
        // Darwin 的 accept 可继承非阻塞标记；连接读写使用有超时的阻塞模式。
        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) & ~O_NONBLOCK)
        var timeout = timeval(tv_sec: 3, tv_usec: 0); var yes: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, socklen_t(MemoryLayout<timeval>.size))
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, socklen_t(MemoryLayout<Int32>.size))
    }
    static func send(_ object: [String:Any], to fd: Int32) throws {
        var data = try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]); data.append(10)
        guard data.count <= 65536 else { throw error("控制消息过大") }
        try data.withUnsafeBytes { bytes in
            var offset = 0
            while offset < bytes.count {
                let n = Darwin.send(fd, bytes.baseAddress!.advanced(by: offset), bytes.count - offset, 0)
                guard n > 0 else { throw error("控制连接写入失败") }; offset += n
            }
        }
    }
    static func receive(_ fd: Int32) throws -> [String:Any] {
        var data = Data(); var buffer = [UInt8](repeating: 0, count: 4096)
        while data.count < 65536 {
            let n = recv(fd, &buffer, buffer.count, 0)
            guard n > 0 else { throw error("控制连接中断或超时") }
            data.append(contentsOf: buffer.prefix(n))
            if let end = data.firstIndex(of: 10) {
                guard let value = try JSONSerialization.jsonObject(with: data.prefix(upTo: end)) as? [String:Any] else { throw error("控制消息格式不正确") }
                return value
            }
        }
        throw error("控制消息过大")
    }
    static func request(_ id: String, action: String) throws -> [String:Any] {
        try prepare(); let fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw error("无法创建控制连接") }; defer { close(fd) }; configure(fd)
        var a = try address(socketPath(id))
        let connected = withUnsafePointer(to: &a) { ptr in ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) } }
        guard connected == 0 else { throw error("模块尚未运行") }
        try send(["protocolVersion": version, "action": action], to: fd)
        let result = try receive(fd)
        guard result["protocolVersion"] as? Int == version, result["id"] as? String == id else { throw error("模块协议不兼容") }
        guard result["ok"] as? Bool == true else { throw error(result["error"] as? String ?? "模块操作失败") }
        return result
    }
}

final class ModuleServer {
    private var fd: Int32 = -1; private var lock: Int32 = -1
    private var source: DispatchSourceRead?; private var path = ""
    func start(id: String, handler: @escaping @MainActor (String) async -> [String:Any]) throws -> Bool {
        try ModuleIPC.prepare(); path = ModuleIPC.socketPath(id)
        lock = open(path + ".lock", O_CREAT | O_RDWR | O_NOFOLLOW, 0o600)
        guard lock >= 0 else { throw ModuleIPC.error("无法锁定模块") }
        guard flock(lock, LOCK_EX | LOCK_NB) == 0 else { close(lock); lock = -1; return false }
        unlink(path); fd = socket(AF_UNIX, SOCK_STREAM, 0)
        guard fd >= 0 else { throw ModuleIPC.error("无法创建模块服务") }
        var a = try ModuleIPC.address(path)
        let result = withUnsafePointer(to: &a) { ptr in ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(fd, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) } }
        guard result == 0, chmod(path, 0o600) == 0, listen(fd, 8) == 0 else { throw ModuleIPC.error("模块控制服务启动失败") }
        _ = fcntl(fd, F_SETFL, O_NONBLOCK)
        let socketFD = fd; let queue = DispatchQueue(label: "cyan.module.ipc", qos: .utility)
        let reader = DispatchSource.makeReadSource(fileDescriptor: fd, queue: queue)
        reader.setEventHandler {
            let client = accept(socketFD, nil, nil); guard client >= 0 else { return }; ModuleIPC.configure(client)
            DispatchQueue.global(qos: .utility).async {
                do {
                    let request = try ModuleIPC.receive(client)
                    guard request["protocolVersion"] as? Int == ModuleIPC.version, let action = request["action"] as? String else { close(client); return }
                    Task { @MainActor in
                        let response = await handler(action)
                        DispatchQueue.global(qos: .utility).async { try? ModuleIPC.send(response, to: client); close(client) }
                    }
                } catch { close(client) }
            }
        }
        source = reader; reader.resume(); return true
    }
    func stop() {
        source?.cancel(); source = nil
        if fd >= 0 { close(fd); fd = -1; unlink(path) }
        if lock >= 0 { flock(lock, LOCK_UN); close(lock); lock = -1 }
    }
    deinit { stop() }
}
