# Claude Companion

English · [简体中文](README.md) · [日本語](README.ja.md)

An unofficial macOS desktop companion for Claude. It shows a draggable mascot and local status cards for activity, approval requests, and the end of a response. Built with Swift, AppKit, and SwiftUI with GPT assistance.

## Interface language

Open ✦ in the menu bar and choose Interface language → 简体中文, 日本語, or English. You can also switch from the character’s context menu or the Activity window. The companion starts in Simplified Chinese and remembers the selection across launches. Claude window controls are recognized using separate matchers.

## Screenshots

The mascot window running in the public preview.

![Claude Companion · Screenshots](screenshots/desktop-mascot.png)

## Build and try

Run the build from this folder with macOS 14 or later and Xcode Command Line Tools. Open the locally signed app in dist and use the menu’s demo to preview the status cards.

~~~sh
./build.sh
open 'dist/Claude Companion Preview.app' --args --demo-only
~~~

## Claude Desktop integration

Grant the preview app macOS Accessibility permission if you want to observe a readable Claude Desktop window. The app uses button labels, the native window title, and the conversation address to infer status. It cannot approve actions. Background windows, cloud tasks, and all Claude versions have not been verified. Claude Code event handling is present in the source. This preview does not install hooks or change Claude settings.

The source preview bundles the GPT-redrawn four-state sprite sheet. Original upstream images, installers, and signing credentials are omitted.

## Character artwork credits

The local edition originally used the unofficial Claude Orange Scholar character from [fywdy/chatgpt-chibi-pets](https://github.com/fywdy/chatgpt-chibi-pets). A later local sprite sheet was generated using GPT's image tool with that character as a reference. Upstream artwork is marked CC BY-NC 4.0. This preview includes the redrawn sheet for noncommercial use. See the [bundled artwork credits](Assets/ClaudeOrangeScholar/SOURCE.md). The original upstream artwork is not bundled.
