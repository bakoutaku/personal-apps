# Claude Companion

简体中文 · [日本語](README.ja.md) · [English](README.en.md)

一个面向 Claude 的非官方 macOS 桌宠。由 GPT 辅助开发，使用 Swift、AppKit 和 SwiftUI。目前公开的是 **0.3.8 源码预览版**。

## 切换界面语言

点开菜单栏的 ✦，在「界面语言」选择简体中文、日本語或 English。右键桌宠或打开活动列表也能切换。默认使用简体中文，应用会记住选择。此选项只控制桌宠界面，Claude 窗口控件识别使用自己的匹配规则。

## 界面截图

公开预览版中实际运行的桌宠角色。

![Claude Companion · 界面截图](screenshots/desktop-mascot.png)

## 功能

- 桌宠可以拖动并记住位置，单击可收起或展开提示。
- 状态卡会提示正在回复、需要授权或本轮回复结束。需要授权时请回到 Claude 窗口操作。
- 菜单可暂停观察、打开诊断、预览提示卡，以及打开自定义形象目录。
- 活动列表可查看本次运行的近期提醒；退出后列表不会保留。

## 构建与演示

需要 macOS 14 或以上及 Xcode 命令行工具。从仓库根目录运行：

```sh
cd claude-companion
./build.sh
open 'dist/Claude Companion Preview.app' --args --demo-only
```

构建脚本会运行核心测试并生成本地签名的应用。先从菜单栏打开演示即可查看通知卡，无需辅助功能权限，也不会调用 Claude。

## 连接 Claude 桌面端

如需实时观察，先退出演示，再正常打开应用。打开「系统设置 → 隐私与安全性 → 辅助功能」，添加并开启 **Claude Companion Preview**。保留一个可读取的 Claude 对话窗口，先用较长的回复测试，再从桌宠菜单查看「连接状态与说明」。

应用在本机读取按钮标签、原生窗口标题和会话地址，判断生成是否开始或结束，不读取回复正文。本轮结束也可能是手动停止，不能据此判断任务成功。切换会话、窗口不可读或状态不明确时，应用会放弃本轮判断。后台或最小化窗口、云端任务以及不同 Claude 版本的兼容性尚未全面验证。

源码保留 Claude Code 本地事件处理入口。预览版不会安装 hooks、修改 Claude 设置或替用户批准操作。

## 角色素材来源

早期本机版使用了 [fywdy/chatgpt-chibi-pets](https://github.com/fywdy/chatgpt-chibi-pets) 的「Claude 橙书娘」同人素材。后来，本机版用 GPT 的图像生成工具参考原形象重绘了四状态图集。上游美术按其声明采用 CC BY-NC 4.0。这里保留参考来源，GPT 重绘版也沿用这一素材来源说明。

公开源码预览随附 GPT 参考原形象重绘的四状态图集，供非商业使用。署名、改绘说明和许可见 [随附素材说明](Assets/ClaudeOrangeScholar/SOURCE.md)。原图、旧安装包和本机签名凭据未随仓库发布。
