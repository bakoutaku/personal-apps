import Foundation

enum Activity: String, Codable { case idle, working, approval, completed, unknown, offline }

/// Only conversation URLs identify sessions. Native window titles are display
/// metadata, never identity; arbitrary AX headings are not read at all.
struct ConversationIdentity {
    static let fallbackTitle = "Claude 当前会话"
    let session: String
    let title: String
    let sourceDescription: String

    static func sessionKey(_ text: String) -> String? {
        guard let url = URLComponents(string: text),
              url.scheme?.lowercased() == "https",
              let host = url.host?.lowercased(), ["claude.ai", "claude.com"].contains(host),
              url.user == nil, url.password == nil,
              url.port == nil || url.port == 443 else { return nil }
        let parts = url.percentEncodedPath.split(separator: "/")
        guard parts.count == 2, ["chat", "cowork"].contains(String(parts[0])) else { return nil }
        let identifier = String(parts[1])
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        guard !identifier.isEmpty, identifier.count <= 128,
              identifier.unicodeScalars.allSatisfy({ allowed.contains($0) }) else { return nil }
        let path = "/\(parts[0])/\(identifier)"
        guard url.percentEncodedPath == path || url.percentEncodedPath == path + "/" else { return nil }
        // Tracking/query parameters and anchors are not a conversation change.
        return "https://\(host)\(path)"
    }

    static func resolve(urls: [String], windowTitle: String) -> ConversationIdentity {
        let keys = Set(urls.compactMap(sessionKey))
        let title = windowTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let isGeneric = ["claude", "claude desktop", "claude cowork", "cowork"].contains(title.lowercased())
        let displayTitle = !title.isEmpty && title.count <= 120 && !isGeneric && !title.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
            ? title : fallbackTitle
        return ConversationIdentity(session: keys.count == 1 ? keys.first! : "", title: displayTitle,
                                    sourceDescription: keys.count == 1 ? "会话地址" : (keys.isEmpty ? "无可靠会话地址" : "会话地址冲突"))
    }
}

struct Observation {
    var session: String
    var title: String
    var buttons: [String]
    var readable: Bool
    var running: Bool = true
    var truncated: Bool = false

    // Presence is useful even in a partial tree. Absence is not: a partial
    // Send/voice-input sample cannot prove that generation has stopped.
    var hasUsableEvidence: Bool {
        guard running, readable, !session.isEmpty else { return false }
        if !truncated { return true }
        let state = ControlClassifier.classify(self)
        return state == .working || state == .approval
    }
}

struct CompanionEvent {
    var session: String
    var title: String
    var activity: Activity
    var date: Date
    var demo = false
}

/// Classifies controls only. Conversation text is never searched for trigger words.
enum ControlClassifier {
    static func normalized(_ text: String) -> String {
        text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
    static let stops: Set<String> = ["stop", "stop response", "stop generating", "stop generation", "stop task", "停止", "停止生成", "停止回复", "停止响应", "停止任务", "応答を停止", "生成を停止", "停止する", "タスクを停止"]
    static let allows: Set<String> = ["allow", "allow once", "approve", "approve once", "允许", "允许一次", "仅允许一次", "批准", "批准一次", "許可", "一度だけ許可", "今回のみ許可", "許可する"]
    static let denies: Set<String> = ["deny", "reject", "don't allow", "do not allow", "拒绝", "不允许", "拒否", "許可しない"]
    static let senders: Set<String> = ["send", "send message", "发送", "发送消息", "送信", "メッセージを送信"]
    static let composers: Set<String> = ["voice input", "start dictation", "dictate", "use voice", "语音输入", "语音", "音声入力", "ディクテーションを開始"]

    static func classify(_ observation: Observation) -> Activity {
        if !observation.running { return .offline }
        guard observation.readable else { return .unknown }
        let labels = Set(observation.buttons.map(normalized))
        if !labels.isDisjoint(with: allows) && !labels.isDisjoint(with: denies) { return .approval }
        if !labels.isDisjoint(with: stops) { return .working }
        // Positive idle evidence avoids interpreting an empty/incomplete tree as completion.
        if !labels.isDisjoint(with: senders) || !labels.isDisjoint(with: composers) { return .idle }
        return .unknown
    }
}

/// Completion requires a seen working turn and two positive idle observations in that session.
/// Partial positive controls may arm a turn or request attention, but never
/// count as the idle evidence needed for a completed event.
final class TransitionTracker {
    struct State {
        var armed = false
        var idleSamples = 0
        var approvalNotified = false
        var lastSeen = Date.distantPast
    }
    private var states: [String: State] = [:]
    private var previousSession: String?
    var current: Activity = .unknown

    func reset() { states.removeAll(); previousSession = nil; current = .unknown }

    func consume(_ o: Observation, now: Date = Date()) -> CompanionEvent? {
        current = ControlClassifier.classify(o)
        guard o.hasUsableEvidence else {
            // Lost visibility invalidates an armed turn: do not infer what happened while blind.
            states.removeAll(); previousSession = nil
            return nil
        }
        if previousSession != o.session {
            // Returning to an old tab is not evidence of a finished response.
            states.removeAll()
            previousSession = o.session
        }
        var state = states[o.session] ?? State()
        if now.timeIntervalSince(state.lastSeen) > 12 { state = State() }
        state.lastSeen = now
        var result: CompanionEvent?
        switch current {
        case .working:
            state.armed = true; state.idleSamples = 0; state.approvalNotified = false
        case .approval:
            state.idleSamples = 0
            if !state.approvalNotified {
                result = CompanionEvent(session: o.session, title: o.title, activity: .approval, date: now)
                state.approvalNotified = true
            }
        case .idle:
            state.idleSamples += 1
            if state.armed && state.idleSamples >= 2 {
                result = CompanionEvent(session: o.session, title: o.title, activity: .completed, date: now)
                state.armed = false
            }
            state.approvalNotified = false
        case .unknown:
            state.armed = false; state.idleSamples = 0
        default: break
        }
        states[o.session] = state
        return result
    }
}
