# Claude Companion

English · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

An unofficial macOS desktop companion for Claude. It shows a draggable mascot and local status cards for activity, approval requests, and the end of a response. Built with Swift, AppKit, and SwiftUI with GPT assistance.

## Build and try

Run the build from this folder with macOS 14 or later and Xcode Command Line Tools. Open the locally signed app in dist and use the menu’s demo to preview the status cards.

~~~sh
./build.sh
open 'dist/Claude Companion Preview.app'
~~~

## Claude Desktop integration

Grant the preview app macOS Accessibility permission if you want to observe a readable Claude Desktop window. The app uses button labels, the native window title, and the conversation address to infer status. It cannot approve actions. Background windows, cloud tasks, and all Claude versions have not been verified. Claude Code event handling is present in the source. This preview does not install hooks or change Claude settings.

The source preview bundles its own simple mascot. Third-party character art, installers, and signing credentials are omitted.
