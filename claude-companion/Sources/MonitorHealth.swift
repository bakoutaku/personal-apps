import Foundation

enum MonitorHealth: String {
    case checking, permissionRequired, notRunning, unavailable, multipleWindows, incomplete, unidentified, connected
    static func evaluate(trusted: Bool, observations: [Observation]) -> MonitorHealth {
        guard trusted else { return .permissionRequired }
        if observations.count == 1, observations[0].running == false { return .notRunning }
        guard observations.count <= 1 else { return .multipleWindows }
        guard let observation = observations.first, observation.readable else { return .unavailable }
        guard !observation.session.isEmpty else { return .unidentified }
        guard observation.hasUsableEvidence else { return .incomplete }
        return .connected
    }
    var title: String {
        switch self {
        case .checking: return "正在连接"
        case .permissionRequired: return "需要辅助功能权限"
        case .notRunning: return "Claude 尚未启动"
        case .unavailable: return "窗口暂时不可读"
        case .multipleWindows: return "多个窗口待确认"
        case .incomplete: return "窗口读取不完整"
        case .unidentified: return "无法识别会话"
        case .connected: return "已连接"
        }
    }
    var shortTitle: String {
        switch self {
        case .permissionRequired: return "需要系统权限"
        case .notRunning: return "等待启动"
        case .unavailable, .incomplete: return "读取受限"
        case .multipleWindows: return "多个窗口"
        case .unidentified: return "会话未识别"
        default: return title
        }
    }
    var guidance: String {
        switch self {
        case .checking: return "正在检查 Claude 的可读取窗口。"
        case .permissionRequired: return "在系统设置的辅助功能中开启 ClaudeCompanion，然后返回这里查看连接状态。"
        case .notRunning: return "打开 Claude，并保留一个对话窗口。"
        case .unavailable: return "将 Claude 的对话窗口显示出来；隐藏或最小化时可能无法识别。"
        case .multipleWindows: return "当前有多个可读取窗口，暂停完成判断以免串会话。请只保留一个对话窗口再试。"
        case .incomplete: return "这次窗口内容读取不完整，暂不判断回复完成。"
        case .unidentified: return "没有读到唯一可靠的会话地址；请打开具体对话。若当前版本不提供地址，桌宠会暂停事件提醒，避免串会话。"
        case .connected: return "仅观察当前可读取会话；后台或隐藏任务可能无法识别。"
        }
    }
}
