import SwiftUI
import AppKit

struct PassportPage: View {
    @ObservedObject var store: PassportBridgeStore
    var p: GrovePalette
    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            SectionHeading(eyebrow: "AI PASSPORT / VOICE LINK", title: "把声音，带到家里的每个角落。", subtitle: "连接你选择的 Agent 后端。设备短按 OK 拨打或挂断，长按切换静音。")
            HStack(alignment: .top, spacing: 20) {
                VStack(alignment: .leading, spacing: 14) {
                    HStack { Image(systemName: "phone.connection.fill").font(.system(size: 23)).foregroundStyle(p.accent); Spacer(); Circle().fill(store.running ? Color.green : p.secondary.opacity(0.4)).frame(width: 8, height: 8); Text(store.running ? "桥接运行中" : "桥接已停止").font(.system(size: 11, weight: .medium)) }
                    Text(store.running ? store.runtime?.title ?? "正在启动" : "准备好，就接通。").font(.system(size: 25, weight: .medium))
                    Text(store.runtime.map { "\($0.listenHost):\($0.port) · " + ($0.deviceConnected ? "AI Passport 已连接" : "等待设备上线") } ?? "启动后，已配对的设备会自动连接这台 Mac。").font(.system(size: 12)).foregroundStyle(p.secondary)
                    HStack(spacing: 10) {
                        Button(store.running ? "停止桥接" : "启动桥接") { Task { if store.running { await store.stop() } else { await store.start() } } }.buttonStyle(.borderedProminent).tint(p.accent)
                        Button("重启") { Task { await store.restart() } }.buttonStyle(.bordered).disabled(!store.running)
                        Spacer(); if store.busy { ProgressView().controlSize(.small) }
                    }.disabled(store.busy)
                }.padding(24).frame(maxWidth: .infinity, minHeight: 175, alignment: .topLeading).background(p.card, in: RoundedRectangle(cornerRadius: 22))

            }
            HStack { Button("准备 Python 运行环境") { Task { await store.prepareRuntime() } }; Text("首次使用需联网安装语音依赖。").font(.caption).foregroundStyle(.secondary) }.disabled(store.busy)
            if let error = store.error { Label(error, systemImage: "exclamationmark.circle").font(.system(size: 12)).foregroundStyle(.orange).textSelection(.enabled) }
            if let notice = store.notice { Label(notice, systemImage: "checkmark.circle").font(.system(size: 12)).foregroundStyle(p.accent) }
            VStack(alignment: .leading, spacing: 14) {
                HStack { Text("首次配网与新设备配对").font(.system(size: 16, weight: .semibold)); Spacer(); Button("允许新设备配对") { Task { await store.allowPairing() } }.disabled(store.busy) }
                Text("手机扫描设备屏幕上的 Wi-Fi 二维码，加入临时热点，在网页选择家庭 Wi-Fi，再搜索并选择这台电脑。设备已配对时，可在未通话状态长按下键重新配网。").font(.system(size: 12)).foregroundStyle(p.secondary).fixedSize(horizontal: false, vertical: true)
                if !store.pairingCode.isEmpty {
                    Text(store.pairingCode).font(.system(size: 23, weight: .medium, design: .monospaced)).foregroundStyle(p.accent).textSelection(.enabled)
                    HStack { if let expires = store.pairingExpires { Text("有效至 \(expires.formatted(date: .omitted, time: .shortened))，成功后自动失效。").font(.system(size: 11)).foregroundStyle(p.secondary) }; Spacer(); Button("关闭配对窗口") { store.closePairing() } }
                }
                if store.running && store.runtime?.discoveryState == "error" { Text("局域网发现服务未能启动，请检查最近运行事件。").font(.system(size: 11)).foregroundStyle(.orange) }
            }.padding(24).background(p.card, in: RoundedRectangle(cornerRadius: 20))
            VStack(alignment: .leading, spacing: 17) {
                HStack { Text("会话与权限").font(.system(size: 16, weight: .semibold)); Spacer(); Button(store.modelLoading ? "读取中…" : "刷新可用模型") { Task { await store.loadModels() } }.font(.system(size: 11)).disabled(store.modelLoading) }
                HStack { Text("Agent 后端").frame(width: 140, alignment: .leading); Picker("Agent 后端", selection: $store.configuration.backendChoice) { Text("Codex").tag("codex"); Text("Hermes Agent").tag("hermes") }.labelsHidden().pickerStyle(.segmented).frame(maxWidth: 360); Spacer() }
                Text(store.configuration.backendChoice == "hermes" ? "Hermes 使用本地语音识别 → Agent 执行 → macOS 语音播报，自动断句；处理和播报期间暂停收音。Hermes 与 Codex 各自保留独立会话。" : "Codex 使用已验证的 WebRTC 实时语音链路，任务由独立 Codex 会话执行。").font(.system(size: 11)).foregroundStyle(p.secondary).fixedSize(horizontal: false, vertical: true)
                HStack { Text("执行任务的模型").frame(width: 140, alignment: .leading); Picker("执行任务的模型", selection: $store.configuration.taskModel) { Text("跟随 Codex 默认").tag(""); ForEach(store.models) { Text($0.name).tag($0.id) } }.labelsHidden().frame(maxWidth: 360); Spacer() }
                HStack { Text("执行权限").frame(width: 140, alignment: .leading); Picker("执行权限", selection: $store.configuration.permissionMode) { Text("只读").tag("readonly"); Text("工作区可写").tag("workspace"); Text("Bypass Permission").tag("bypass") }.labelsHidden().pickerStyle(.segmented).frame(maxWidth: 470); Spacer() }
                Text(permissionDescription).font(.system(size: 11)).foregroundStyle(p.secondary).fixedSize(horizontal: false, vertical: true)
                HStack { Text("工作目录").frame(width: 140, alignment: .leading); TextField("任务工作目录", text: $store.configuration.workspace).textFieldStyle(.roundedBorder); Button("选择…") { store.chooseWorkspace() } }
                HStack { Text("语音模型").frame(width: 140, alignment: .leading); Text(store.configuration.backendChoice == "hermes" ? "Whisper base · 本地 / Tingting · macOS" : (store.configuration.voiceModel.isEmpty ? "CLI 默认 · gpt-live-1-codex" : store.configuration.voiceModel)).font(.system(size: 12, design: .monospaced)).foregroundStyle(p.secondary); Spacer() }
            }.font(.system(size: 12)).padding(24).background(p.card, in: RoundedRectangle(cornerRadius: 20))
            VStack(alignment: .leading, spacing: 16) {
                Text("启动与连接").font(.system(size: 16, weight: .semibold))
                Toggle("随 Cyan Passport 启动语音桥", isOn: $store.configuration.autoStart).toggleStyle(.switch).tint(p.accent)
                Toggle("桥接运行时保持 Mac 唤醒", isOn: $store.configuration.keepAwake).toggleStyle(.switch).tint(p.accent)
                Text("关闭工作台窗口后仍可通话；退出 Cyan Passport 会停止由它启动的桥接。自动启动使用 Cyan Passport 现有的系统登录项。").font(.system(size: 11)).foregroundStyle(p.secondary)
                DisclosureGroup("高级连接设置") {
                    VStack(alignment: .leading, spacing: 12) {
                        TextField("监听地址（auto 自动选择当前网络）", text: $store.configuration.listenHost)
                        TextField("监听端口", value: $store.configuration.port, format: .number.grouping(.never))
                        TextField("语音模型覆盖（留空沿用 CLI 默认）", text: $store.configuration.voiceModel)
                        TextField("Python 运行环境", text: $store.configuration.pythonPath)
                        TextField("Hermes Gateway 地址", text: $store.configuration.gatewayURL)
                        TextField("任务模型标识（留空跟随后端默认）", text: $store.configuration.taskModel)
                        Text("设备仍保存着配对的 Mac 地址和端口；更改地址或端口后，需要通过 USB 更新设备配对。").font(.system(size: 10)).foregroundStyle(p.secondary)
                    }.textFieldStyle(.roundedBorder).padding(.top, 10)
                }.font(.system(size: 12))
                HStack { Text(store.dirty ? "有尚未保存的修改" : "配置已保存").font(.system(size: 10)).foregroundStyle(p.secondary); Spacer(); Button("保存配置") { _ = store.save() }; Button(store.running ? "保存并重启桥接" : "保存并启动") { Task { await store.restart() } }.buttonStyle(.borderedProminent).tint(p.accent) }.disabled(store.busy)
            }.font(.system(size: 12)).padding(24).background(p.card, in: RoundedRectangle(cornerRadius: 20))
            VStack(alignment: .leading, spacing: 12) {
                HStack { Text("最近运行事件").font(.system(size: 14, weight: .medium)); Spacer(); Button("打开数据目录") { store.openDataDirectory() }.font(.system(size: 11)) }
                Text(store.logExcerpt).font(.system(size: 10, design: .monospaced)).foregroundStyle(p.secondary).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                Text("配对密钥仅保存在这台 Mac。这里不会显示 Wi-Fi 密码、登录令牌或语音正文。").font(.system(size: 10)).foregroundStyle(p.secondary)
            }.padding(22).background(p.card, in: RoundedRectangle(cornerRadius: 20))
        }
    }
    var permissionDescription: String {
        switch store.configuration.permissionMode {
        case "bypass": return "完全访问本机文件与网络，Codex CLI 执行不再请求审批。macOS 的系统权限与授权仍然有效。"
        case "readonly": return "仅查看文件；需要写入或更多权限时，当前桥不会代你批准。"
        default: return "允许修改工作目录内的文件；网络受限，额外执行权限需要审批。"
        }
    }
}
