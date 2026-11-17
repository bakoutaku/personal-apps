import Foundation
import CoreGraphics

func check(_ value: @autoclosure () -> Bool, _ message: String) {
    if !value() { fatalError(message) }
}

@main struct CoreTests {
    static func main() {
        var animationChanges = 0
        let celebration = CompletionAnimation { animationChanges += 1 }
        check(celebration.name(for: .idle) == "idle", "Idle never celebrates")
        let completionTracker = TransitionTracker()
        let work = Observation(session: "animation-turn", title: "Test", buttons: ["Stop"], readable: true)
        let ready = Observation(session: "animation-turn", title: "Test", buttons: ["Send"], readable: true)
        _ = completionTracker.consume(work)
        _ = completionTracker.consume(ready)
        let finished = completionTracker.consume(ready)
        check(finished?.activity == .completed, "Use detected completion rather than animation preview")
        if finished?.activity == .completed { celebration.start(duration: 0.04) }
        check(celebration.name(for: .completed) == "jumping", "Detected completion jumps immediately")
        check(celebration.name(for: .working) == "running" && celebration.name(for: .approval) == "waiting", "New task state takes precedence over celebration")
        check(completionTracker.consume(ready) == nil, "Idle polling does not restart celebration")
        RunLoop.main.run(until: Date().addingTimeInterval(0.10))
        check(celebration.name(for: .completed) == "review" && animationChanges == 2, "Expiry switches to review and invalidates UI without another poll")
        check(finished?.activity == .completed, "Presentation expiry leaves event state intact")
        celebration.start(duration: 0.02)
        celebration.start(duration: 0.15)
        let restartChanges = animationChanges
        RunLoop.main.run(until: Date().addingTimeInterval(0.07))
        check(celebration.isCelebrating && animationChanges == restartChanges, "Old deadline cannot end a newer celebration")
        celebration.cancel()
        let cancelledChanges = animationChanges
        RunLoop.main.run(until: Date().addingTimeInterval(0.16))
        check(!celebration.isCelebrating && animationChanges == cancelledChanges, "Cancelled timer cannot update UI later")
        check(celebration.name(for: .completed) == "review" && celebration.name(for: .unknown) == "idle", "Interrupted celebration never leaks into unknown state")
        check(CompletionAnimation.duration == 3.5, "Production celebration interval")
        print("PASS: detected completion jump/review, timer-driven UI refresh, new-task priority, restart and cancellation")
        let urlA = "https://claude.ai/chat/session-a"
        let urlB = "https://claude.ai/chat/session-b"
        let original = ConversationIdentity.resolve(urls: [urlA], windowTitle: "Claude")
        check(original.session == urlA && original.title == "Claude 当前会话", "Generic native title uses safe label")
        let renamed = ConversationIdentity.resolve(urls: [urlA + "?source=desktop#bottom"], windowTitle: "新的对话标题")
        check(renamed.session == original.session && renamed.title == "新的对话标题", "Renaming and URL decorations preserve identity")
        let other = ConversationIdentity.resolve(urls: [urlB], windowTitle: "新的对话标题")
        check(other.session != renamed.session, "Identical display names do not merge conversations")
        check(ConversationIdentity.resolve(urls: [], windowTitle: "独特的窗口标题").session.isEmpty, "Window title alone cannot identify conversation")
        check(ConversationIdentity.resolve(urls: [urlA, urlB], windowTitle: "Claude").session.isEmpty, "Conflicting URLs do not select an arbitrary session")
        check(ConversationIdentity.resolve(urls: [urlA, urlA + "/?x=1"], windowTitle: "Claude").session == urlA, "Repeated equivalent URLs are unambiguous")
        for invalid in ["https://claude.ai/", "https://claude.ai/chat/", "https://claude.ai/settings/chat/session-a", "https://claude.ai/chat/a/extra", "https://claude.ai//chat/a", "https://claude.ai/chat/a%2Fb", "https://claude.ai.evil.test/chat/a", "http://claude.ai/chat/a", "https://user@claude.ai/chat/a", "https://claude.ai:8443/chat/a"] {
            check(ConversationIdentity.sessionKey(invalid) == nil, "Non-conversation/malformed URLs cannot identify a session")
        }
        check(ConversationIdentity.sessionKey("https://claude.com/cowork/task-1") == "https://claude.com/cowork/task-1", "Cowork URL supported")
        for name in ["", "Claude Desktop", "Cowork", String(repeating: "字", count: 121), "第一行\n第二行"] {
            check(ConversationIdentity.resolve(urls: [urlA], windowTitle: name).title == "Claude 当前会话", "Unsafe or generic names use safe label")
        }
        let identityTracker = TransitionTracker()
        _ = identityTracker.consume(Observation(session: original.session, title: original.title, buttons: ["Stop"], readable: true))
        _ = identityTracker.consume(Observation(session: renamed.session, title: renamed.title, buttons: ["Send"], readable: true))
        check(identityTracker.consume(Observation(session: renamed.session, title: renamed.title, buttons: ["Send"], readable: true))?.activity == .completed, "Rename does not interrupt completion")
        _ = identityTracker.consume(Observation(session: renamed.session, title: renamed.title, buttons: ["Stop"], readable: true))
        _ = identityTracker.consume(Observation(session: other.session, title: other.title, buttons: ["Send"], readable: true))
        check(identityTracker.consume(Observation(session: other.session, title: other.title, buttons: ["Send"], readable: true)) == nil, "Same-title navigation cannot create completion")
        print("PASS: safe title metadata, stable URL identity, rename, same-title navigation and missing/conflicting URLs")
        check(PetGeometry.normalized(.nan) == 1 && PetGeometry.normalized(.infinity) == 1, "Invalid scale defaults safely")
        let screen = CGRect(x: -1280, y: 20, width: 1280, height: 720)
        let anchor = CGRect(x: -900, y: 100, width: 172, height: 210)
        for scale in [0.6, 1.0, 1.6] {
            let frame = PetGeometry.scaledFrame(anchor, scale: scale, screen: screen)
            check(frame.midX == anchor.midX && frame.minY == anchor.minY, "Scale preserves bottom center")
            let edge = PetGeometry.scaledFrame(CGRect(x: -173, y: 650, width: 172, height: 210), scale: scale, screen: screen)
            let insets = PetGeometry.clearInsets(scale: scale)
            let visible = CGRect(x: edge.minX + insets.left, y: edge.minY, width: edge.width - insets.left - insets.right, height: edge.height)
            check(screen.contains(visible), "Scaled pet stays on negative-origin display")
            let right = PetGeometry.clampedOrigin(CGRect(x: -10, y: 100, width: edge.width, height: edge.height), scale: scale, screen: screen)
            check(right.x + edge.width - insets.right == screen.maxX, "Visible pet can reach the right edge")
        }
        print("PASS: scale bounds, invalid settings, stable anchor and screen edges")
        var history = EventHistory()
        let event = CompanionEvent(session: "a", title: "Test", activity: .approval, date: Date())
        let id = history.insert(event)
        history.markRead(id)
        check(history.records.count == 1 && history.unreadCount == 0, "Read events remain in history")
        for _ in 0..<25 { _ = history.insert(event) }
        check(history.records.count == 20 && history.unreadCount == 20, "History is bounded")
        history.markAllRead()
        check(history.records.count == 20 && history.unreadCount == 0, "Mark all read preserves history")
        history.clear()
        check(history.records.isEmpty, "Clear history")
        print("PASS: history read/retain, capacity, mark all and clear")
        let valid = Observation(session: "a", title: "Test", buttons: ["Stop"], readable: true)
        check(MonitorHealth.evaluate(trusted: false, observations: [valid]) == .permissionRequired, "Permission is not a task state")
        check(MonitorHealth.evaluate(trusted: true, observations: []) == .unavailable, "Missing window is not idle")
        check(MonitorHealth.evaluate(trusted: true, observations: [valid, valid]) == .multipleWindows, "Ambiguous windows")
        var partial = valid; partial.truncated = true
        check(MonitorHealth.evaluate(trusted: true, observations: [partial]) == .connected, "Partial positive Stop is useful evidence")
        partial.buttons = ["Send"]
        check(MonitorHealth.evaluate(trusted: true, observations: [partial]) == .incomplete, "Partial Send cannot imply idle")
        partial = valid; partial.session = ""
        check(MonitorHealth.evaluate(trusted: true, observations: [partial]) == .unidentified, "Missing session identity")
        partial = valid; partial.running = false; partial.readable = false
        check(MonitorHealth.evaluate(trusted: true, observations: [partial]) == .notRunning, "App not running")
        check(MonitorHealth.evaluate(trusted: true, observations: [valid]) == .connected, "Positive connection evidence")
        print("PASS: permission, missing window, ambiguity, partial data and connection classification")
        let t = TransitionTracker()
        func sample(_ buttons: [String], session: String = "a", readable: Bool = true, truncated: Bool = false) -> Observation {
            Observation(session: session, title: "Test", buttons: buttons, readable: readable, truncated: truncated)
        }
        check(t.consume(sample(["发送消息"])) == nil, "Historical idle must not notify")
        check(t.consume(sample(["停止生成"])) == nil, "Working arms only")
        check(t.consume(sample(["发送消息"])) == nil, "Debounce first sample")
        check(t.consume(sample(["发送消息"]))?.activity == .completed, "Chinese completion")
        check(t.consume(sample(["发送消息"])) == nil, "No duplicate completion")
        check(t.consume(sample(["Allow once", "Deny"]))?.activity == .approval, "Approval pair")
        check(t.consume(sample(["Allow once", "Deny"])) == nil, "No duplicate approval")
        check(ControlClassifier.classify(sample(["I will allow once and deny later"])) == .unknown, "Substring false positive")
        check(ControlClassifier.classify(sample(["Allow once"])) == .unknown, "Must have deny too")
        _ = t.consume(sample(["Stop response"]))
        _ = t.consume(sample(["Send message"], session: "b"))
        check(t.consume(sample(["Send message"], session: "b")) == nil, "Navigation never completes")
        _ = t.consume(sample(["Stop"]))
        _ = t.consume(sample([], readable: false))
        _ = t.consume(sample(["Send"]))
        check(t.consume(sample(["Send"])) == nil, "Unreadable tree invalidates completion")
        _ = t.consume(sample(["Stop"]))
        _ = t.consume(sample(["Send"], truncated: true))
        check(t.consume(sample(["Send"])) == nil, "Truncated tree never completes")
        _ = t.consume(sample(["Stop"]))
        _ = t.consume(sample([]))
        _ = t.consume(sample(["Send"]))
        check(t.consume(sample(["Send"])) == nil, "Unknown transition never completes")
        check(ControlClassifier.classify(sample(["今回のみ許可", "許可しない"])) == .approval, "Japanese approval")
        let clock = Date(timeIntervalSince1970: 100)
        t.reset()
        _ = t.consume(sample(["Stop"]), now: clock)
        _ = t.consume(sample(["Send"]), now: clock.addingTimeInterval(20))
        check(t.consume(sample(["Send"]), now: clock.addingTimeInterval(22)) == nil, "Sleep gap never completes")
        print("PASS: transition, deduplication, navigation, missing data, approval localization, sleep gap")
        t.reset()
        check(t.consume(sample(["Stop"], truncated: true)) == nil, "Partial Stop arms without completing")
        check(t.current == .working, "Partial Stop remains working")
        _ = t.consume(sample(["Send"]))
        check(t.consume(sample(["Send"]))?.activity == .completed, "Partial work plus two complete idle samples completes")
        t.reset()
        check(t.consume(sample(["Allow once", "Deny"], truncated: true))?.activity == .approval, "Partial approval pair notifies")
        check(t.consume(sample(["Allow once", "Deny"], truncated: true)) == nil, "Partial approval is deduplicated")
        check(t.consume(sample(["Allow once"], truncated: true)) == nil, "Incomplete approval pair stays silent")
        t.reset()
        _ = t.consume(sample(["Stop"], truncated: true))
        _ = t.consume(sample(["Send"], truncated: true))
        _ = t.consume(sample(["Send"]))
        check(t.consume(sample(["Send"])) == nil, "Blind idle gap invalidates partial work")
        t.reset()
        _ = t.consume(sample(["Stop"], truncated: true))
        _ = t.consume(sample(["Send"], session: "b"))
        check(t.consume(sample(["Send"], session: "b")) == nil, "Partial work cannot complete another conversation")
        check(!sample(["Stop"], session: "", truncated: true).hasUsableEvidence, "Partial controls need session identity")
        check(!sample(["Stop"], readable: false, truncated: true).hasUsableEvidence, "Partial controls need readable window")
        print("PASS: partial working/approval, complete idle debounce, blind gaps and navigation safeguards")
        for screen in [CGRect(x: 0, y: 25, width: 1440, height: 850), CGRect(x: -1280, y: 0, width: 1280, height: 720)] {
            for origin in [CGPoint(x: screen.minX, y: screen.minY), CGPoint(x: screen.maxX - 176, y: screen.maxY - 210), CGPoint(x: screen.midX, y: screen.midY)] {
                let pet = CGRect(origin: origin, size: CGSize(width: 176, height: 210))
                for height in [120.0, 380.0, 1200.0] {
                    let card = CardPlacement.frame(pet: pet, cards: CGSize(width: 340, height: height), screen: screen)
                    check(card.minX >= screen.minX && card.maxX <= screen.maxX, "Card horizontal bounds")
                    check(card.minY >= screen.minY && card.maxY <= screen.maxY, "Card vertical bounds")
                    check(pet.origin == origin && pet.size == CGSize(width: 176, height: 210), "Notifications must not alter the pet anchor")
                }
            }
        }
        print("PASS: notification placement at screen edges and on a negative-origin display")
    }
}
