#!/bin/zsh
set -euo pipefail
cd "${0:A:h}"

mkdir -p build dist
xcrun swiftc Sources/{CodeHooks,MonitorCore}.swift Tests/CodeHooksTests.swift -o build/code-hook-tests
./build/code-hook-tests
xcrun swiftc Sources/{CodeHooks,MonitorCore,CompletionAnimation,CardPlacement,PetGeometry,EventHistory,MonitorHealth}.swift Tests/CoreTests.swift -o build/core-tests
./build/core-tests

stage=$(mktemp -d "${TMPDIR:-/tmp}/companion-preview.XXXXXX")
trap 'rm -rf -- "$stage"' EXIT
app="$stage/Claude Companion Preview.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/ClaudeOrangeScholar"
cp Assets/ClaudeOrangeScholar/* "$app/Contents/Resources/ClaudeOrangeScholar/"
xcrun swiftc -O Sources/*.swift -framework AppKit -framework SwiftUI -framework ApplicationServices -framework ImageIO -o "$app/Contents/MacOS/ClaudeCompanion"
cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleIdentifier</key><string>com.bakoutaku.claudecompanion.preview</string>
<key>CFBundleName</key><string>Claude Companion Preview</string>
<key>CFBundleExecutable</key><string>ClaudeCompanion</string>
<key>CFBundleVersion</key><string>14</string>
<key>CFBundleShortVersionString</key><string>0.3.8</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$app"
codesign --verify --strict "$app"
dest="$PWD/dist/${app:t}"
rm -rf -- "$dest"
ditto "$app" "$dest"
codesign --verify "$dest"
print -r -- "Built: $dest"
