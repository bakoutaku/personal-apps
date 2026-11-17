import Foundation

/// A presentation timer only. Expiry never changes task state, event cards,
/// read status, or the completion detector.
final class CompletionAnimation {
    static let duration: TimeInterval = 3.5
    private(set) var isCelebrating = false
    private var expiry: DispatchWorkItem?
    private var generation = UUID()
    private let onChange: () -> Void

    init(onChange: @escaping () -> Void) { self.onChange = onChange }
    deinit { expiry?.cancel() }

    func start(duration: TimeInterval = CompletionAnimation.duration) {
        expiry?.cancel()
        let token = UUID()
        generation = token
        isCelebrating = true
        onChange()
        let item = DispatchWorkItem { [weak self] in
            guard let self, self.generation == token else { return }
            self.expiry = nil
            self.isCelebrating = false
            self.onChange()
        }
        expiry = item
        DispatchQueue.main.asyncAfter(deadline: .now() + duration, execute: item)
    }

    func cancel() {
        expiry?.cancel(); expiry = nil; generation = UUID()
        if isCelebrating { isCelebrating = false; onChange() }
    }

    func name(for activity: Activity) -> String {
        switch activity {
        case .working: return "running"
        case .approval: return "waiting"
        case .completed: return isCelebrating ? "jumping" : "review"
        default: return "idle"
        }
    }
}
