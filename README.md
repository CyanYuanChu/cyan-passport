# Cyan Passport

AI Passport 语音桥。可独立运行，无需安装 Cyan Grove；也可由 [Cyan Grove](https://github.com/CyanYuanChu/cyangrove) 安装和控制。

## 下载

从 [Releases](https://github.com/CyanYuanChu/cyan-passport/releases) 下载 `Cyan-Passport-macOS-arm64.zip`，解压并放入应用程序目录。最低 macOS 14.0，当前预览包仅支持 Apple Silicon。

当前版本是 **开发预览版**：安装包使用 ad hoc 签名，未做 Developer ID 公证，macOS 可能阻止首次打开。不要关闭系统安全保护；需要常规免拦截安装的用户请等待正式签名版。

## 独立使用

打开 App 后使用自己的窗口和菜单栏。关闭窗口保留后台运行；菜单中的退出才结束本模块。登录启动在 App 的设置中配置。

## 接入 Grove

通过用户私有目录中的 Unix socket 接受协议 v1 的状态、打开窗口、刷新和退出请求；不会要求 Grove 常驻，也不会监听 TCP 网络端口。Grove 退出不会结束本模块。

## 从源码构建

需要 Xcode（含 Command Line Tools）、Python 3。运行 `./scripts/build.sh`，产物在 `build/Cyan Passport.app`；运行 `./scripts/check.sh` 做模块自检与签名检查。构建脚本无需其他本地仓库。`CODE_SIGN_IDENTITY` 可指定你自己的签名身份。

## 数据

配置和数据由模块自身保存。检测到旧 Cyan Grove 安装时，只迁移本模块的已知配置；卸载 App 默认保留数据。所有运行时数据、配对密钥和本地会话均不进入仓库或安装包。

## 进程验收

`python3 scripts/test-runtime.py` 验证真实进程的单实例、socket 权限、未知动作拒绝、菜单栏模式切换与干净退出。测试跳过快捷键监听及语音桥自动启动，不会发起语音任务。

## 运行前提

默认使用本机 Codex CLI。首次可点击“准备 Python 运行环境”，需要 Python 3.10–3.14 和联网下载依赖。已有旧配置会保留原工作目录、执行权限和 Python 路径。语音桥绑定已有设备端口前，请先结束并停止旧版桥接；不会接管或停止其他来源的桥进程。

Hermes 是从当前开发版本保留的实验适配器，需要另外配置 Hermes Gateway、专用 hermes-key 和本地 Whisper base 模型；运行环境按钮只安装 Python 依赖，不自动下载模型或配置 Gateway。此次没有对该适配器做完整设备语音验收。
