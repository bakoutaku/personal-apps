import Foundation

@main struct CodeHooksTests {
    static func main() throws {
        let now = Date()
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: dir) }
        func event(_ name: String, _ sid: String = "one", offset: Double = 0) -> CodeHookEvent {
            let input = "{\"session_id\":\"\(sid)\",\"hook_event_name\":\"\(name)\",\"notification_type\":\"permission_prompt\",\"prompt\":\"SECRET_PROMPT\",\"tool_input\":{\"command\":\"SECRET_COMMAND\"},\"transcript_path\":\"/DO_NOT_READ\",\"last_assistant_message\":\"SECRET_REPLY\"}"
            return CodeHookEvent.sanitize(Data(input.utf8), now: now.addingTimeInterval(offset))!
        }
        let tracker = CodeHookTracker(started: now.addingTimeInterval(-1))
        let start = event("UserPromptSubmit")
        try CodeHookStore.write(start, to: dir)
        let saved = try String(contentsOf: dir.appendingPathComponent(start.id + ".json"), encoding: .utf8)
        assert(!saved.contains("SECRET") && !saved.contains("DO_NOT_READ") && !saved.contains("one"))
        assert(tracker.drain(directory: dir, now: now).isEmpty)
        assert(tracker.current(now: now)?.1 == .working)
        assert(tracker.consume(event("PermissionRequest", offset: 1), now: now.addingTimeInterval(1))?.activity == .approval)
        assert(tracker.consume(event("Notification", offset: 2), now: now.addingTimeInterval(2)) == nil)
        assert(tracker.consume(event("PostToolUse", offset: 3), now: now.addingTimeInterval(3)) == nil)
        assert(tracker.current(now: now.addingTimeInterval(3))?.1 == .working)
        let stop = event("Stop", offset: 4)
        assert(tracker.consume(stop, now: now.addingTimeInterval(4))?.activity == .completed)
        assert(tracker.consume(stop, now: now.addingTimeInterval(4)) == nil)
        assert(tracker.consume(event("Stop", "unseen", offset: 4), now: now.addingTimeInterval(4)) == nil)
        assert(tracker.consume(event("UserPromptSubmit", "two", offset: 5), now: now.addingTimeInterval(5)) == nil)
        assert(tracker.current(now: now.addingTimeInterval(5))?.1 == .working)
        _ = tracker.consume(event("PermissionRequest", "three", offset: 6), now: now.addingTimeInterval(6))
        assert(tracker.current(now: now.addingTimeInterval(6))?.1 == .approval)
        _ = tracker.consume(event("SessionEnd", "three", offset: 7), now: now.addingTimeInterval(7))
        assert(tracker.current(now: now.addingTimeInterval(7))?.1 == .working)
        _ = tracker.consume(event("StopFailure", "two", offset: 8), now: now.addingTimeInterval(8))
        assert(tracker.current(now: now.addingTimeInterval(8))?.1 == .unknown)
        assert(tracker.current(now: now.addingTimeInterval(1900)) == nil)
        assert(tracker.consume(event("UserPromptSubmit", "old", offset: -10), now: now) == nil)
        assert(CodeHookEvent.sanitize(Data("{}".utf8)) == nil)
        assert(CodeHookEvent.sanitize(Data("{\"session_id\":\"x\",\"hook_event_name\":\"SubagentStop\"}".utf8)) == nil)
        assert(CodeHookEvent.sanitize(Data("{\"session_id\":\"x\",\"hook_event_name\":\"Notification\",\"notification_type\":\"idle_prompt\"}".utf8)) == nil)
        let remaining = try FileManager.default.contentsOfDirectory(atPath: dir.path)
        assert(remaining.isEmpty)
        print("PASS: Code hook privacy allowlist, atomic queue, start/approval/resume/stop, dedupe, multi-session priority, failure, silent expiry and old-event rejection (OFFLINE only)")
    }
}
