import AppKit
import ApplicationServices

struct MonitorReport {
    var observations: [Observation]
    var diagnostic: () -> String
    var trusted: Bool
}

final class ClaudeObserver {
    static let bundleID = "com.anthropic.claudefordesktop"
    private let queue = DispatchQueue(label: "local.claudecompanion.observer", qos: .utility)
    private var busy = false

    func poll(_ receive: @escaping (MonitorReport) -> Void) {
        guard !busy else { return }
        busy = true
        queue.async {
            let report = self.scan()
            DispatchQueue.main.async { self.busy = false; receive(report) }
        }
    }

    private func value(_ element: AXUIElement, _ name: String) -> CFTypeRef? {
        var output: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, name as CFString, &output) == .success else { return nil }
        return output
    }
    private func string(_ element: AXUIElement, _ name: String) -> String {
        let v = value(element, name)
        if let text = v as? String { return text }
        if let url = v as? URL { return url.absoluteString }
        return ""
    }
    private func elements(_ element: AXUIElement, _ name: String) -> [AXUIElement] {
        value(element, name) as? [AXUIElement] ?? []
    }

    private func attributes(_ element: AXUIElement, _ names: [String]) -> ([Any], Bool) {
        var raw: CFArray?
        guard AXUIElementCopyMultipleAttributeValues(element, names as CFArray, [], &raw) == .success,
              let values = raw as? [Any], values.count == names.count else { return ([], false) }
        // Unsupported optional attributes are normal; a failed AX request is not.
        let complete = !values.contains { item in
            guard CFGetTypeID(item as CFTypeRef) == AXValueGetTypeID() else { return false }
            let value = item as! AXValue
            guard AXValueGetType(value) == .axError else { return false }
            var error = AXError.success
            return AXValueGetValue(value, .axError, &error) && error != .success && error != .noValue && error != .attributeUnsupported
        }
        return (values, complete)
    }
    private func structure(_ element: AXUIElement) -> (role: String?, children: [AXUIElement], complete: Bool) {
        let (values, complete) = attributes(element, [kAXRoleAttribute, kAXChildrenAttribute])
        guard values.count == 2 else { return (nil, [], false) }
        return (values[0] as? String, values[1] as? [AXUIElement] ?? [], complete)
    }
    private func controlLabels(_ element: AXUIElement) -> (text: [String], complete: Bool) {
        let (values, complete) = attributes(element, [kAXTitleAttribute, kAXDescriptionAttribute, kAXHelpAttribute])
        return (values.compactMap { $0 as? String }, complete)
    }

    private func scan() -> MonitorReport {
        guard AXIsProcessTrusted() else {
            return MonitorReport(observations: [], diagnostic: { localized("需要辅助功能权限。菜单 → 开启辅助功能设置。") }, trusted: false)
        }
        guard let app = NSRunningApplication.runningApplications(withBundleIdentifier: Self.bundleID).first else {
            return MonitorReport(observations: [Observation(session: "", title: "Claude", buttons: [], readable: false, running: false)], diagnostic: { localized("Claude 尚未运行。") }, trusted: true)
        }
        let root = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(root, 0.2)
        // Chromium/Electron's accessibility attribute requests the web content tree.
        // This only enables accessibility for the running process; app files/settings are untouched.
        AXUIElementSetAttributeValue(root, "AXManualAccessibility" as CFString, kCFBooleanTrue)
        let windows = elements(root, kAXWindowsAttribute).prefix(4)
        var observations: [Observation] = []
        var counts: [() -> String] = []
        for window in windows {
            // Visit the newest/lower branches first (usually the composer),
            // instead of letting a long transcript consume the whole budget.
            // Read role + children in one AX request; never read message values.
            var pending: [(AXUIElement, Int, Bool)] = [(window, 0, false)]
            var cursor = 0
            var buttons: [String] = []
            // Read native window metadata and WebArea URL only. Do not inspect
            // AXHeading titles/descriptions: they can be generated message text.
            var documents = [string(window, kAXDocumentAttribute)]
            var seenWeb = false
            var readable = false
            let started = ProcessInfo.processInfo.systemUptime
            var incomplete = false
            while let (node, depth, insideWeb) = pending.popLast() {
                if cursor >= 12000 || ProcessInfo.processInfo.systemUptime - started > 1.2 {
                    incomplete = true; break
                }
                cursor += 1
                let snapshot = structure(node)
                guard let role = snapshot.role else { incomplete = true; continue }
                if !snapshot.complete { incomplete = true }
                let inWeb = insideWeb || role == "AXWebArea"
                if role == "AXWebArea" {
                    seenWeb = true
                    let url = string(node, kAXURLAttribute)
                    documents.append(url)
                }
                if inWeb && (role == kAXButtonRole || role == kAXPopUpButtonRole || role == "AXMenuButton") {
                    readable = true
                    let labels = controlLabels(node)
                    if !labels.complete { incomplete = true }
                    buttons.append(contentsOf: labels.text.filter { !$0.isEmpty && $0.count <= 100 })
                }
                if depth < 35 {
                    pending.append(contentsOf: snapshot.children.map { ($0, depth + 1, inWeb) })
                } else if !snapshot.children.isEmpty {
                    incomplete = true
                }
            }
            let windowTitle = string(window, kAXTitleAttribute)
            let identity = ConversationIdentity.resolve(urls: documents, windowTitle: windowTitle)
            let session = identity.session
            let truncated = incomplete
            observations.append(Observation(session: session, title: identity.title, buttons: buttons, readable: readable && seenWeb, truncated: truncated))
            let observation = observations[observations.count - 1]
            let judgment = truncated
                ? (observation.hasUsableEvidence ? "仅采用明确的工作/授权控件" : "证据不足，未判断完成")
                : "完整扫描"
            let seen = readable && seenWeb
            let elapsed = Int((ProcessInfo.processInfo.systemUptime - started) * 1000)
            let titleSource = identity.title == ConversationIdentity.fallbackTitle ? "通用名称" : "原生窗口标题"
            let known = Set(buttons.map(ControlClassifier.normalized)).intersection(ControlClassifier.stops.union(ControlClassifier.allows).union(ControlClassifier.denies).union(ControlClassifier.senders).union(ControlClassifier.composers)).sorted()
            let labelSummary = known.joined(separator: "/")
            let count = cursor
            counts.append {
                localized("控件 {0} · 可读 {1} · 会话标识 {2} · 标题来源 {3} · 完整 {4} · 用时 {5}ms · 判断 {6} · 状态控件 {7}",
                          count, localized(seen ? "是" : "否"), localized(identity.sourceDescription),
                          localized(titleSource), localized(truncated ? "否" : "是"), elapsed,
                          localized(judgment), labelSummary)
            }
        }
        return MonitorReport(observations: observations, diagnostic: { counts.isEmpty ? localized("Claude 窗口不可读取；可能已隐藏或最小化。") : counts.map { $0() }.joined(separator: "\n") }, trusted: true)
    }
}
