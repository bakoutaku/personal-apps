import Foundation
import CryptoKit

/// The hook process discards all content fields. Never follow transcript_path,
/// inspect tool_input, or emit a hook decision (including on errors).
struct CodeHookEvent: Codable {
    var id: String
    var session: String
    var name: String
    var notification: String?
    var date: Date
    static let names: Set<String> = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest", "PostToolUse", "PostToolUseFailure", "Notification", "Stop", "StopFailure", "SessionEnd"]
    static func sanitize(_ data: Data, now: Date = Date()) -> CodeHookEvent? {
        struct Input: Decodable {
            let session_id: String
            let hook_event_name: String
            let notification_type: String?
        }
        guard data.count <= 4 * 1024 * 1024,
              let input = try? JSONDecoder().decode(Input.self, from: data),
              !input.session_id.isEmpty, input.session_id.utf8.count <= 256,
              names.contains(input.hook_event_name) else { return nil }
        let session = SHA256.hash(data: Data(input.session_id.utf8)).map { String(format: "%02x", $0) }.joined()
        let notification = input.notification_type == "permission_prompt" ? "permission_prompt" : nil
        if input.hook_event_name == "Notification" && notification == nil { return nil }
        return CodeHookEvent(id: UUID().uuidString, session: session, name: input.hook_event_name, notification: notification, date: now)
    }
}

enum CodeHookStore {
    static var directory: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/ClaudeCompanionPreview/CodeEvents", isDirectory: true)
    }
    static func write(_ event: CodeHookEvent, to directory: URL = directory) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let url = directory.appendingPathComponent(event.id + ".json")
        try JSONEncoder().encode(event).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        // Keep the queue bounded even when the pet is not running. These are
        // sanitized status records only; stale events never imply completion.
        let files = (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.contentModificationDateKey])) ?? []
        let records = files.filter { $0.pathExtension == "json" }
        if records.count > 512 {
            let sorted = records.sorted {
                ((try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast) <
                ((try? $1.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast)
            }
            for old in sorted.prefix(records.count - 512) { try? FileManager.default.removeItem(at: old) }
        }
    }
    static func run() {
        // No stdout/stderr, no allow/deny/continue/block output, always exit 0.
        // Read at most 4MiB + 1; oversized input is discarded without persisting it.
        var input = Data()
        while input.count <= 4 * 1024 * 1024 {
            let chunk = FileHandle.standardInput.readData(ofLength: 65536)
            if chunk.isEmpty { break }
            input.append(chunk)
        }
        if let event = CodeHookEvent.sanitize(input) { try? write(event) }
    }
}

/// Independent from AX: permission for window observation cannot gate Code events.
final class CodeHookTracker {
    struct State { var activity: Activity; var date: Date; var armed: Bool }
    private(set) var states: [String: State] = [:]
    private var seen = Set<String>()
    private var seenOrder: [String] = []
    private(set) var started: Date
    private(set) var lastEvent: CodeHookEvent?
    init(started: Date = Date()) { self.started = started }
    func reset() { states.removeAll(); started = Date() }
    func consume(_ event: CodeHookEvent, now: Date = Date()) -> CompanionEvent? {
        guard !seen.contains(event.id), event.date >= started,
              event.date <= now.addingTimeInterval(5), now.timeIntervalSince(event.date) < 60,
              event.session.count == 64, event.session.allSatisfy({ $0.isHexDigit }),
              CodeHookEvent.names.contains(event.name) else { return nil }
        seen.insert(event.id); seenOrder.append(event.id)
        if seenOrder.count > 1024 { seen.remove(seenOrder.removeFirst()) }
        lastEvent = event
        var state = states[event.session] ?? State(activity: .unknown, date: event.date, armed: false)
        guard event.date >= state.date else { return nil }
        let previous = state.activity
        state.date = event.date
        var notification: Activity?
        switch event.name {
        case "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure":
            state.activity = .working; state.armed = true
        case "PermissionRequest", "Notification":
            state.activity = .approval
            if previous != .approval { notification = .approval }
        case "Stop":
            if state.armed { state.activity = .completed; notification = .completed }
            else { state.activity = .idle }
            state.armed = false
        case "SessionEnd": states.removeValue(forKey: event.session); return nil
        case "StopFailure": state.activity = .unknown; state.armed = false
        default: state.activity = .idle; state.armed = false
        }
        states[event.session] = state
        if states.count > 64, let oldest = states.min(by: { $0.value.date < $1.value.date })?.key { states.removeValue(forKey: oldest) }
        guard let notification else { return nil }
        return CompanionEvent(session: "code:" + event.session, title: "Claude Code · 会话 " + event.session.prefix(6), activity: notification, date: event.date)
    }
    func current(now: Date = Date()) -> (String, Activity)? {
        // Silent expiry never invents completion. Long-running work needs a new
        // real event after 30 minutes; old idle/completed sessions yield to AX.
        let active = states.filter { entry in
            let age = now.timeIntervalSince(entry.value.date)
            return age >= -5 && age < ((entry.value.activity == .working || entry.value.activity == .approval) ? 1800 : 15)
        }
        let chosen = active.max { a, b in
            func rank(_ value: Activity) -> Int { value == .approval ? 3 : (value == .working ? 2 : 1) }
            if rank(a.value.activity) != rank(b.value.activity) { return rank(a.value.activity) < rank(b.value.activity) }
            return a.value.date < b.value.date
        }
        return chosen.map { ("code:" + $0.key, $0.value.activity) }
    }
    func drain(directory: URL = CodeHookStore.directory, now: Date = Date()) -> [CompanionEvent] {
        let urls = (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])) ?? []
        var events: [(URL, CodeHookEvent)] = []
        for url in urls where url.pathExtension == "json" {
            guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]),
                  values.isRegularFile == true, values.isSymbolicLink != true,
                  (values.fileSize ?? Int.max) < 2048,
                  let data = try? Data(contentsOf: url), let event = try? JSONDecoder().decode(CodeHookEvent.self, from: data) else { continue }
            events.append((url, event))
        }
        return events.sorted { $0.1.date < $1.1.date }.compactMap { url, event in
            let result = consume(event, now: now)
            try? FileManager.default.removeItem(at: url)
            return result
        }
    }
}
