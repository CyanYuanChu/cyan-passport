# Cyan Passport

同一份原生功能包支持在 [Cyan Grove](https://github.com/CyanYuanChu/cyangrove) 内完整使用，也支持独立运行。

## 在 Grove 中使用

在「功能管理」开启对应功能。Grove 下载本仓库的功能包，将模块自己的完整原生界面嵌入当前窗口，无需打开独立软件。界面和业务逻辑均由模块提供，可以单独更新；已加载模块的更新在重启 Grove 后生效。

配对、桥接启停、模型权限与 Python 环境准备均在 Grove 内操作，需要 Python 3.10–3.14。旧桥运行时拒绝重复启动，不会结束原通话。Hermes 为实验适配器，另需 Gateway、hermes-key 和 Whisper base 模型，新设备语音尚待完整实机验收。

## 独立使用与下载

从 [Releases](https://github.com/CyanYuanChu/cyan-passport/releases) 下载所需产物：

- `Cyan-Passport-module-macOS-arm64.zip`：Grove 使用的原生功能包。
- `Cyan-Passport-macOS-arm64.zip`：独立版 App，内嵌完全相同的功能包。
- `module.json` 和 `SHA256SUMS`：身份、接口、版本及两个安装包的摘要。

独立版放入应用程序目录即可使用，不依赖 Grove。两种模式共用配置和数据；单实例锁避免同一功能被两处同时启用。

## 构建与验证

需要 Xcode 和 Python 3，无需父仓库或其他 Cyan 项目。

```sh
./scripts/build.sh
./scripts/check.sh
python3 scripts/test-runtime.py
python3 scripts/package-release.py
```

构建生成 `build/cyan-passport.groveplugin` 与 `build/Cyan Passport.app`。业务源码只编译一次，独立 App 是加载同一功能包的薄入口。原生 ABI v2 通过 Objective-C 桥提供 NSViewController 和生命周期。

Grove 验证五模块单进程集成与独立版互斥；独立版验证功能自检、单实例控制与退出。更新不动态卸载已加载的 Swift 代码。

当前为 Apple Silicon 开发预览版，最低 macOS 14。使用 ad hoc 签名，尚未做 Developer ID 公证，macOS 可能拦截首次打开。请勿关闭系统安全保护。用户数据及配对凭据不进入仓库和安装包。
