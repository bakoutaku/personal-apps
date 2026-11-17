# Claude Companion

[English](README.md) · 简体中文 · [日本語](README.ja.md)

面向 Claude 的非官方 macOS 桌宠。角色可拖动，会在本机显示工作状态、授权提醒和本轮回复结束提示。使用 Swift、AppKit 和 SwiftUI，由 GPT 辅助开发。

## 构建与试用

需要 macOS 14 或以上及 Xcode 命令行工具。在本目录执行构建，打开 dist 中本地签名的应用。菜单中的演示可以预览状态卡。

~~~sh
./build.sh
open 'dist/Claude Companion Preview.app'
~~~

## Claude 桌面端联动

如需观察 Claude 桌面端，请给预览版授予 macOS 辅助功能权限。桌宠根据可读窗口的按钮标签、原生窗口标题和会话地址判断状态，不能替你批准操作。后台窗口、云端任务及所有 Claude 版本尚未验证。源码保留 Claude Code 事件处理，预览版不会安装 hooks 或修改 Claude 设置。

公开源码版使用内置简易角色，未打包第三方立绘、安装器或签名凭据。
