import AppKit
import SwiftUI
import ApplicationServices

struct Card: Identifiable {
    let id: UUID
    let event: CompanionEvent
    init(event: CompanionEvent, id: UUID = UUID()) { self.event = event; self.id = id }
}

final class CompanionModel: ObservableObject {
    @Published var activity: Activity = .unknown
    @Published var cards: [Card] = []
    @Published var history = EventHistory()
    var showActivity: (() -> Void)?
    @Published var detail = "正在检查 Claude…"
    @Published var health: MonitorHealth = .checking
    @Published var currentTitle: String?
    @Published var lastChecked: Date?
    private var completedSession: String?
    var statusText: String {
        if paused { return "已暂停" }
        return health == .connected ? activityLabel(activity) : health.shortTitle
    }
    var taskText: String {
        if paused { return "观察已暂停" }
        return health == .connected ? activityLabel(activity) : "暂时无法确认"
    }
    @Published var trusted = false
    @Published var paused = false
    @Published var expanded = true
    @Published var silent = true
    @Published var skinEpoch = 0
    @Published var demoAnimation: String?
    @Published var petScale = PetGeometry.normalized(UserDefaults.standard.object(forKey: "petScale") as? Double ?? 1)
    var showAppearance: (() -> Void)?
    var scaleChanged: (() -> Void)?
    func setScale(_ value: Double) {
        petScale = PetGeometry.normalized(value)
        UserDefaults.standard.set(petScale, forKey: "petScale")
        scaleChanged?()
    }
    private lazy var completionAnimation = CompletionAnimation { [weak self] in self?.objectWillChange.send() }
    var resized: (() -> Void)?
    let observer = ClaudeObserver()
    let tracker = TransitionTracker()
    let codeTracker = CodeHookTracker()
    @Published var codeDiagnostic = "尚未收到 Claude Code 事件；如已手动启用 hooks，请新开本地 Code 会话。"
    private var codeSelectedSession: String?
    var timer: Timer?
    var lastEvent: Date?
    var pausedAt: Date?
    var showDetails: (() -> Void)?
    var dragFinished: (() -> Void)?

    func start() {
        silent = UserDefaults.standard.object(forKey: "silent") as? Bool ?? true
        tick()
        timer = Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in self?.tick() }
    }
    func applyCodeStatus() -> Bool {
        guard let (session, state) = codeTracker.current() else { codeSelectedSession = nil; return false }
        if codeSelectedSession != session { completionAnimation.cancel() }
        codeSelectedSession = session
        health = .connected; detail = codeDiagnostic; currentTitle = "Claude Code · 会话 " + session.dropFirst(5).prefix(6)
        activity = state
        if state != .completed { completionAnimation.cancel() }
        return true
    }
    func tick() {
        guard !paused else { return }
        let events = codeTracker.drain()
        if let last = codeTracker.lastEvent {
            codeDiagnostic = "已接收本机 Code hook：\(last.name) · \(last.date.formatted(date: .omitted, time: .standard))。仅保存事件类型与不可逆会话摘要。"
        }
        // Apply selected session before the event presentation so a new session
        // cannot inherit or cancel another session's completion timer.
        let usingCode = applyCodeStatus()
        for event in events {
            if event.activity == .completed && event.session == codeSelectedSession { completionAnimation.start() }
            add(event)
        }
        if usingCode { tracker.reset(); completedSession = nil; lastChecked = Date(); return }
        observer.poll { [weak self] report in
            guard let self, !self.paused else { return }
            guard self.codeTracker.current() == nil else { return }
            self.trusted = report.trusted
            self.detail = report.diagnostic
            self.lastChecked = Date()
            self.health = MonitorHealth.evaluate(trusted: report.trusted, observations: report.observations)
            guard self.health == .connected, let o = report.observations.first else {
                self.completionAnimation.cancel()
                self.tracker.reset(); self.completedSession = nil; self.currentTitle = nil
                self.activity = self.health == .notRunning ? .offline : .unknown
                return
            }
            self.currentTitle = o.title
            let event = self.tracker.consume(o)
            if self.tracker.current != .idle || self.completedSession != o.session { self.completedSession = nil }
            if event?.activity == .completed { self.completedSession = o.session; self.completionAnimation.start() }
            self.activity = self.tracker.current == .idle && self.completedSession == o.session ? .completed : self.tracker.current
            if self.activity != .completed { self.completionAnimation.cancel() }
            if let event { self.add(event) }
        }
    }
    func add(_ event: CompanionEvent) {
        if let i = cards.firstIndex(where: { $0.event.session == event.session && $0.event.demo == event.demo }) { cards.remove(at: i) }
        let recordID = history.insert(event)
        cards.insert(Card(event: event, id: recordID), at: 0)
        if cards.count > 3 { cards = Array(cards.prefix(3)) }
        lastEvent = event.date; expanded = true
        if !silent { NSSound(named: "Glass")?.play() }
        resized?()
    }
    func demo(_ type: Activity) {
        add(CompanionEvent(session: "demo", title: "演示 · 桌宠联动预览", activity: type, date: Date(), demo: true))
        previewAnimation(type == .approval ? "waiting" : "jumping")
    }
    var animationName: String {
        if let demoAnimation { return demoAnimation }
        if paused { return "idle" }
        return completionAnimation.name(for: activity)
    }
    func previewAnimation(_ name: String) {
        demoAnimation = name
        let version = UUID(); previewVersion = version
        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            if self?.previewVersion == version { self?.demoAnimation = nil }
        }
    }
    private var previewVersion = UUID()
    func reloadSkin() { PetGeometry.artInsets = PetAssets.horizontalInsets(); skinEpoch += 1; resized?(); dragFinished?() }
    func dismiss(_ id: UUID) { cards.removeAll { $0.id == id }; history.markRead(id); resized?() }
    func clearCards() { for card in cards { history.markRead(card.id) }; cards.removeAll(); resized?() }
    func clearHistory() { history.clear(); cards.removeAll(); resized?() }
    func openClaude() {
        if let app = NSRunningApplication.runningApplications(withBundleIdentifier: ClaudeObserver.bundleID).first { app.activate(options: []) }
        else if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: ClaudeObserver.bundleID) { NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration()) }
    }
    func permissionSettings() {
        NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)
    }
    func pauseToggle() { paused.toggle(); completionAnimation.cancel(); tracker.reset(); codeTracker.reset(); completedSession = nil; activity = .unknown; if !paused { tick() } }
}

func activityLabel(_ state: Activity) -> String {
    switch state {
    case .working: return "Claude 正在回复"
    case .approval: return "Claude 需要授权"
    case .completed: return "本轮回复已结束"
    case .idle: return "等待输入"
    case .offline: return "等待 Claude 启动"
    case .unknown: return "状态未识别"
    }
}
func activityColor(_ state: Activity) -> Color {
    switch state {
    case .working: return Color(red: 0.77, green: 0.40, blue: 0.25)
    case .approval: return .orange
    case .completed: return Color(red: 0.26, green: 0.55, blue: 0.43)
    default: return .secondary
    }
}

/// Small original vector placeholder. No downloaded executables, tracking or model API.
struct Mascot: View {
    var activity: Activity
    var animate: Bool
    var body: some View {
        TimelineView(.animation(minimumInterval: 0.15, paused: !animate)) { context in
        let bounce = animate ? sin(context.date.timeIntervalSinceReferenceDate * 2.2) : 0
        ZStack {
            Ellipse().fill(.black.opacity(0.10)).frame(width: 86, height: 12).offset(y: 66)
            ZStack {
                // Soft copper bob, cream clothes and a small book.
                RoundedRectangle(cornerRadius: 31).fill(Color(red: 0.75, green: 0.36, blue: 0.22)).frame(width: 91, height: 83).offset(y: -24)
                Capsule().fill(Color(red: 0.95, green: 0.89, blue: 0.78)).frame(width: 57, height: 62).offset(y: 31)
                RoundedRectangle(cornerRadius: 18).fill(Color(red: 1, green: 0.88, blue: 0.77)).frame(width: 68, height: 59).offset(y: -24)
                Ellipse().fill(Color(red: 0.85, green: 0.46, blue: 0.29)).frame(width: 78, height: 31).rotationEffect(.degrees(-13)).offset(x: -5, y: -49)
                Ellipse().fill(Color(red: 0.77, green: 0.37, blue: 0.23)).frame(width: 23, height: 48).rotationEffect(.degrees(18)).offset(x: 33, y: -34)
                HStack(spacing: 23) {
                    Capsule().fill(Color(red: 0.28, green: 0.21, blue: 0.18)).frame(width: 5, height: activity == .completed ? 3 : 9)
                    Capsule().fill(Color(red: 0.28, green: 0.21, blue: 0.18)).frame(width: 5, height: activity == .completed ? 3 : 9)
                }.offset(y: -22)
                HStack(spacing: 35) { Circle().fill(.pink.opacity(0.35)); Circle().fill(.pink.opacity(0.35)) }.frame(width: 53, height: 8).offset(y: -13)
                Text(activity == .approval ? "○" : "⌣").font(.system(size: 15, weight: .medium)).foregroundStyle(.brown).offset(y: -8)
                HStack(spacing: 23) {
                    Capsule().fill(Color(red: 0.4, green: 0.29, blue: 0.23)); Capsule().fill(Color(red: 0.4, green: 0.29, blue: 0.23))
                }.frame(width: 47, height: 18).offset(y: 63)
                RoundedRectangle(cornerRadius: 4).fill(Color(red: 0.39, green: 0.52, blue: 0.45)).frame(width: 49, height: 32).rotationEffect(.degrees(-7)).offset(y: 35)
                Rectangle().fill(.white.opacity(0.65)).frame(width: 2, height: 27).offset(x: -14, y: 36)
                HStack(spacing: 37) { Circle().fill(Color(red: 1, green: 0.88, blue: 0.77)); Circle().fill(Color(red: 1, green: 0.88, blue: 0.77)) }.frame(width: 62, height: 13).offset(y: 30)
                if activity == .approval {
                    Text("!").font(.system(size: 22, weight: .bold, design: .rounded)).foregroundStyle(.white).frame(width: 28, height: 28).background(.orange, in: Circle()).offset(x: 48, y: -62)
                } else if activity == .working {
                    Text("✦").font(.system(size: 25)).foregroundStyle(Color(red: 0.89, green: 0.58, blue: 0.33)).rotationEffect(.degrees(bounce * 20)).offset(x: 48, y: -57)
                }
            }.offset(y: bounce * 2)
        }
        .frame(width: 150, height: 170)
        .accessibilityLabel("Claude 桌宠，" + activityLabel(activity))
        }
    }
}

/// SwiftUI's hosting view does not reliably forward background window dragging.
/// A native surface over the character separates a real drag from a short click.
final class CharacterDragView: NSView {
    var clicked: (() -> Void)?
    var finished: (() -> Void)?
    var menuActions: [(String, () -> Void)] = []
    private var pointerStart: NSPoint?
    private var windowStart = NSPoint.zero
    private var moved = false
    override var acceptsFirstResponder: Bool { false }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override var mouseDownCanMoveWindow: Bool { false }
    override func mouseDown(with event: NSEvent) {
        pointerStart = NSEvent.mouseLocation
        windowStart = window?.frame.origin ?? .zero
        moved = false
    }
    override func mouseDragged(with event: NSEvent) {
        guard let start = pointerStart, let window else { return }
        let point = NSEvent.mouseLocation
        let dx = point.x - start.x, dy = point.y - start.y
        if !moved && hypot(dx, dy) < 4 { return }
        moved = true
        window.setFrameOrigin(NSPoint(x: windowStart.x + dx, y: windowStart.y + dy))
    }
    override func mouseUp(with event: NSEvent) {
        guard pointerStart != nil else { return }
        pointerStart = nil
        if moved { finished?() } else { clicked?() }
        moved = false
    }
    override func rightMouseDown(with event: NSEvent) {
        // The pet's nonactivating panel deliberately leaves the foreground app alone.
        // Menu tracking, however, must belong to an active app so AppKit can route
        // outside clicks and Escape to dismiss it. Activate only for the menu.
        pointerStart = nil
        moved = false
        NSApp.activate(ignoringOtherApps: true)
        let menu = NSMenu()
        for (index, entry) in menuActions.enumerated() {
            let item = NSMenuItem(title: entry.0, action: #selector(runMenu(_:)), keyEquivalent: "")
            item.target = self; item.tag = index; menu.addItem(item)
        }
        // Also cancel tracking if the user switches apps while the menu is open.
        // Scope the observer to this popup; never observe keyboard events globally.
        let deactivation = NotificationCenter.default.addObserver(
            forName: NSApplication.didResignActiveNotification, object: NSApp, queue: .main
        ) { [weak menu] _ in menu?.cancelTracking() }
        // Accessory/nonactivating windows can keep menu tracking alive even when
        // another app receives a click. Observe mouse-downs only while tracking;
        // no keyboard capture, event suppression, or Accessibility permission.
        let outsideClick = NSEvent.addGlobalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown, .otherMouseDown]
        ) { [weak menu] _ in menu?.cancelTracking() }
        defer {
            NotificationCenter.default.removeObserver(deactivation)
            if let outsideClick { NSEvent.removeMonitor(outsideClick) }
        }
        NSMenu.popUpContextMenu(menu, with: event, for: self)
    }
    @objc private func runMenu(_ sender: NSMenuItem) {
        guard menuActions.indices.contains(sender.tag) else { return }
        menuActions[sender.tag].1()
    }
}

struct CharacterDragSurface: NSViewRepresentable {
    @ObservedObject var model: CompanionModel
    func makeNSView(context: Context) -> CharacterDragView { CharacterDragView() }
    func updateNSView(_ view: CharacterDragView, context: Context) {
        view.clicked = { model.expanded.toggle(); model.resized?() }
        view.finished = { model.dragFinished?() }
        view.menuActions = [
            ("打开 Claude", { model.openClaude() }),
            ("连接状态与使用说明…", { model.showDetails?() }),
            ("人物大小…", { model.showAppearance?() }),
            ("活动列表…", { model.showActivity?() }),
            ("打开自定义形象文件夹…", { PetAssets.openCustomDirectory() }),
            ("重新加载形象", { model.reloadSkin() }),
            ("演示：需要授权", { model.demo(.approval) }),
            ("演示：回复结束", { model.demo(.completed) }),
            ("清除全部提示", { model.clearCards() }),
            (model.paused ? "恢复观察" : "暂停观察", { model.pauseToggle() }),
            ("退出桌宠", { NSApp.terminate(nil) })
        ]
        view.setAccessibilityLabel("Claude 桌宠，可拖动；单击展开提示，右键打开菜单")
    }
}

struct TaskCardsView: View {
    @ObservedObject var model: CompanionModel
    var body: some View {
                VStack(spacing: 8) {
                    ForEach(model.cards) { card in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack {
                                Circle().fill(activityColor(card.event.activity)).frame(width: 7, height: 7)
                                Text((card.event.demo ? "演示 · " : "") + activityLabel(card.event.activity)).font(.system(size: 13, weight: .semibold))
                                Spacer()
                                Button { model.dismiss(card.id) } label: { Image(systemName: "xmark").font(.system(size: 10, weight: .semibold)) }.buttonStyle(.plain).accessibilityLabel("关闭提示")
                            }
                            Text(card.event.title).font(.system(size: 12)).foregroundStyle(.secondary).lineLimit(2)
                            HStack {
                                Text(card.event.activity == .approval ? "请在 Claude 中查看并决定。" : "已观察到生成停止，请查看结果。").font(.system(size: 11)).foregroundStyle(.secondary)
                                Spacer(minLength: 0)
                                Button("打开 Claude") { model.openClaude() }.font(.system(size: 11, weight: .medium)).buttonStyle(.bordered)
                            }
                        }
                        .padding(13).frame(width: 320, alignment: .leading)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
                        .overlay(RoundedRectangle(cornerRadius: 16).stroke(.white.opacity(0.35), lineWidth: 1))
                        .shadow(color: .black.opacity(0.12), radius: 6, y: 3)
                    }
                }.padding(10).fixedSize()
    }
}

struct PetStatusView: View {
    @ObservedObject var model: CompanionModel
    var body: some View {
        HStack(spacing: 5) {
                    Circle().fill(activityColor(model.activity)).frame(width: 5, height: 5)
                    Text(model.statusText).font(.system(size: 10, weight: .medium))
                    Button { model.showActivity?() } label: {
                        HStack(spacing: 2) {
                            Image(systemName: model.history.unreadCount > 0 ? "bell.badge" : "bell")
                            if model.history.unreadCount > 0 { Text("\(model.history.unreadCount)").monospacedDigit() }
                        }.font(.system(size: 10))
                    }.buttonStyle(.plain).accessibilityLabel("活动列表，\(model.history.unreadCount)条未读")
                }.padding(.horizontal, 9).padding(.vertical, 5).background(.regularMaterial, in: Capsule())
        .fixedSize()
    }
}

struct CompanionView: View {
    @ObservedObject var model: CompanionModel
    var body: some View {
        VStack(alignment: .trailing, spacing: 8) {
            VStack(spacing: 0) {
                Group {
                    if PetAssets.file("idle") != nil {
                        AnimatedPet(state: model.animationName, epoch: model.skinEpoch, paused: model.paused)
                            .frame(width: 150 * model.petScale, height: 170 * model.petScale)
                    } else {
                        Mascot(activity: model.paused ? .idle : model.activity, animate: !model.paused)
                    }
                }.overlay(CharacterDragSurface(model: model))
                Color.clear.frame(width: 150, height: 24)
            }.padding(.trailing, 6)
        }
        .padding(8)
        .fixedSize()
        .preferredColorScheme(nil)
        .contextMenu {
            Button("打开 Claude") { model.openClaude() }
            Button("连接状态与使用说明…") { model.showDetails?() }
            Button("人物大小…") { model.showAppearance?() }
            Button("活动列表…") { model.showActivity?() }
            Button("开启辅助功能设置…") { model.permissionSettings() }
            Button("打开自定义形象文件夹…") { PetAssets.openCustomDirectory() }
            Button("重新加载形象") { model.reloadSkin() }
            Divider()
            Button("演示：需要授权") { model.demo(.approval) }
            Button("演示：回复结束") { model.demo(.completed) }
            Button("清除全部提示") { model.clearCards() }
            Button(model.paused ? "恢复观察" : "暂停观察") { model.pauseToggle() }
            Divider()
            Button("退出桌宠") { NSApp.terminate(nil) }
        }
    }
}

struct ActivityListView: View {
    @ObservedObject var model: CompanionModel
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Circle().fill(model.paused ? Color.secondary : (model.health == .connected ? Color.green : Color.orange)).frame(width: 7, height: 7)
                    Text("连接：" + (model.paused ? "已暂停" : model.health.title)).font(.system(size: 13, weight: .semibold))
                    Spacer()
                    Button("检查连接") { model.tick() }.disabled(model.paused)
                }
                Text("工作：" + model.taskText).font(.callout)
                if let title = model.currentTitle { Text(title).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                Text(model.health.guidance).font(.caption).foregroundStyle(.secondary)
                if model.health == .permissionRequired {
                    Button("打开辅助功能设置") { model.permissionSettings() }.font(.caption)
                }
                if let checked = model.lastChecked {
                    HStack(spacing: 3) {
                        Text("最近检查")
                        Text(checked, style: .time)
                    }.font(.caption2).foregroundStyle(.secondary)
                }
            }.padding(12).background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 12))
            HStack {
                Text("最近活动").font(.headline)
                Spacer()
                Button("全部已读") { model.history.markAllRead() }.disabled(model.history.unreadCount == 0)
                Button("清空记录") { model.clearHistory() }.disabled(model.history.records.isEmpty)
            }
            if model.history.records.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "bell").font(.largeTitle).foregroundStyle(.secondary)
                    Text("还没有活动记录")
                    Text("识别到授权提示或本轮回复结束后，会在这里保留记录。")
                        .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }.frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(model.history.records) { record in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack {
                                    Circle().fill(record.isRead ? Color.secondary : activityColor(record.event.activity)).frame(width: 7, height: 7)
                                    Text((record.event.demo ? "演示 · " : "") + activityLabel(record.event.activity)).font(.system(size: 13, weight: .semibold))
                                    Spacer()
                                    Text(record.event.date, style: .time).font(.caption).foregroundStyle(.secondary)
                                }
                                Text(record.event.title).font(.callout).lineLimit(2)
                                HStack {
                                    Text(record.isRead ? "已读" : "未读").font(.caption).foregroundStyle(.secondary)
                                    Spacer()
                                    if !record.isRead { Button("标为已读") { model.history.markRead(record.id) }.font(.caption) }
                                    Button("打开 Claude") { model.history.markRead(record.id); model.openClaude() }.font(.caption)
                                }
                            }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                                .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                }
            }
            Text("保留本次运行最近20条。已读仅表示看过提醒，不代表授权已处理。")
                .font(.caption).foregroundStyle(.secondary)
        }.padding(18).frame(minWidth: 440, minHeight: 360)
    }
}

struct AppearanceSettingsView: View {
    @ObservedObject var model: CompanionModel
    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("人物大小").font(.headline)
            HStack {
                Text("小").foregroundStyle(.secondary)
                Slider(value: Binding(get: { model.petScale }, set: { model.setScale($0) }), in: 0.6...1.6, step: 0.05)
                    .accessibilityLabel("人物大小")
                Text("大").foregroundStyle(.secondary)
                Text("\(Int((model.petScale * 100).rounded()))%")
                    .monospacedDigit().frame(width: 48, alignment: .trailing)
            }
            Text("实时调整人物大小，提示文字保持原大小。设置会自动保存。")
                .font(.callout).foregroundStyle(.secondary)
            Button("恢复默认大小") { model.setScale(1) }
        }.padding(24).frame(width: 400)
    }
}

class TransparentHost<Content: View>: NSHostingView<Content> {
    override var isOpaque: Bool { false }
    required init(rootView: Content) {
        super.init(rootView: rootView)
        wantsLayer = true; layer?.backgroundColor = NSColor.clear.cgColor
    }
    @MainActor required dynamic init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
}

final class DraggableHost: TransparentHost<CompanionView> {
    override var mouseDownCanMoveWindow: Bool { true }
}

final class PetPanel: NSPanel {
    var moved: (() -> Void)?
    override var canBecomeKey: Bool { false }
    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 1 { super.mouseDown(with: event) }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    let model = CompanionModel()
    var panel: PetPanel!
    var host: DraggableHost!
    var statusPanel: PetPanel!
    var statusHost: NSHostingView<PetStatusView>!
    var cardsPanel: PetPanel!
    var cardsHost: NSHostingView<TaskCardsView>!
    var statusItem: NSStatusItem!
    var diagnosticWindow: NSWindow?
    var appearanceWindow: NSWindow?
    var activityWindow: NSWindow?
    var subscribers: [Any] = []

    func applicationDidFinishLaunching(_ notification: Notification) {
        let others = NSRunningApplication.runningApplications(withBundleIdentifier: Bundle.main.bundleIdentifier ?? "com.bakoutaku.claudecompanion.preview").filter { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }
        if !others.isEmpty { NSApp.terminate(nil); return }
        NSApp.setActivationPolicy(.accessory)
        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(NSMenuItem(title: "退出 Claude 桌宠", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"))
        appItem.submenu = appMenu; mainMenu.addItem(appItem); NSApp.mainMenu = mainMenu
        PetGeometry.artInsets = PetAssets.horizontalInsets()
        panel = PetPanel(contentRect: NSRect(origin: .zero, size: PetGeometry.size(scale: model.petScale)), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "Claude 桌宠"
        panel.isOpaque = false; panel.backgroundColor = .clear; panel.hasShadow = false
        panel.level = .floating; panel.hidesOnDeactivate = false; panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        host = DraggableHost(rootView: CompanionView(model: model)); panel.contentView = host
        panel.setAccessibilityLabel("Claude 桌宠")
        cardsPanel = PetPanel(contentRect: NSRect(x: 0, y: 0, width: 340, height: 120), styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        cardsPanel.title = "Claude 桌宠 · 任务提示"
        cardsPanel.isOpaque = false; cardsPanel.backgroundColor = .clear; cardsPanel.hasShadow = false
        cardsPanel.level = .floating; cardsPanel.hidesOnDeactivate = false
        cardsPanel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        cardsHost = TransparentHost(rootView: TaskCardsView(model: model)); cardsPanel.contentView = cardsHost
        panel.addChildWindow(cardsPanel, ordered: .above)
        statusPanel = PetPanel(contentRect: .zero, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        statusPanel.title = "Claude 桌宠 · 状态"
        statusPanel.isOpaque = false; statusPanel.backgroundColor = .clear; statusPanel.hasShadow = false
        statusPanel.level = .floating; statusPanel.hidesOnDeactivate = false
        statusPanel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        statusHost = TransparentHost(rootView: PetStatusView(model: model)); statusPanel.contentView = statusHost
        panel.addChildWindow(statusPanel, ordered: .above)
        resize()
        let defaults = UserDefaults.standard
        if defaults.object(forKey: "positionX") != nil {
            panel.setFrameOrigin(NSPoint(x: defaults.double(forKey: "positionX"), y: defaults.double(forKey: "positionY")))
            clamp()
        } else if let screen = NSScreen.main {
            panel.setFrameOrigin(NSPoint(x: screen.visibleFrame.maxX - panel.frame.width + PetGeometry.clearInsets(scale: model.petScale).right - 12, y: screen.visibleFrame.minY + 50))
        }
        NotificationCenter.default.addObserver(self, selector: #selector(didMove), name: NSWindow.didMoveNotification, object: panel)
        model.resized = { [weak self] in DispatchQueue.main.async { self?.resize() } }
        model.showDetails = { [weak self] in self?.showDiagnostics() }
        model.showAppearance = { [weak self] in self?.showAppearanceSettings() }
        model.showActivity = { [weak self] in self?.showActivityList() }
        model.scaleChanged = { [weak self] in self?.applyScale() }
        model.dragFinished = { [weak self] in self?.clamp(); self?.didMove() }
        panel.orderFrontRegardless()
        resize()
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "✦"
        statusItem.button?.toolTip = "Claude 桌宠"
        buildMenu()
        subscribers.append(model.objectWillChange.sink { [weak self] _ in DispatchQueue.main.async { self?.placeStatus() } })
        model.start()
        if CommandLine.arguments.contains("--demo") { model.demo(.approval) }
        if !AXIsProcessTrusted(), !defaults.bool(forKey: "didShowIntro") {
            defaults.set(true, forKey: "didShowIntro")
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.7) { self.showDiagnostics() }
        }
    }
    func applyScale() {
        guard let panel, let screen = NSScreen.screens.first(where: { $0.visibleFrame.intersects(panel.frame) }) ?? NSScreen.main else { return }
        let rect = PetGeometry.scaledFrame(panel.frame, scale: model.petScale, screen: screen.visibleFrame)
        panel.setFrame(rect, display: true)
        didMove()
        resize()
    }
    @objc func showActivityList() {
        if let window = activityWindow { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); return }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 480, height: 420), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Claude 桌宠 · 活动列表"
        window.contentView = NSHostingView(rootView: ActivityListView(model: model))
        window.minSize = NSSize(width: 440, height: 360)
        window.isReleasedWhenClosed = false; window.center(); activityWindow = window
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
    @objc func showAppearanceSettings() {
        if let window = appearanceWindow { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true); return }
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 448, height: 190), styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Claude 桌宠 · 人物大小"
        window.contentView = NSHostingView(rootView: AppearanceSettingsView(model: model))
        window.isReleasedWhenClosed = false; window.center()
        appearanceWindow = window
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
    func placeStatus() {
        guard let panel, let statusPanel, let statusHost else { return }
        guard panel.isVisible else { statusPanel.orderOut(nil); return }
        let screen = NSScreen.screens.first(where: { $0.visibleFrame.intersects(panel.frame) }) ?? NSScreen.main
        guard let bounds = screen?.visibleFrame else { return }
        let size = statusHost.fittingSize
        let x = max(bounds.minX + 4, min(panel.frame.midX - 3 - size.width / 2, bounds.maxX - size.width - 4))
        statusPanel.setFrame(CGRect(x: x, y: panel.frame.minY + 8, width: size.width, height: size.height), display: true)
        statusPanel.orderFrontRegardless()
    }
    func resize() {
        placeStatus()
        // The pet window never resizes for notifications. Only the independent cards do.
        guard let panel, let cardsPanel, let cardsHost else { return }
        guard panel.isVisible, model.expanded, !model.cards.isEmpty else {
            cardsPanel.orderOut(nil); return
        }
        cardsHost.rootView = TaskCardsView(model: model)
        cardsHost.layoutSubtreeIfNeeded()
        let fitting = cardsHost.fittingSize
        let size = NSSize(width: max(340, fitting.width), height: max(100, fitting.height))
        cardsPanel.setContentSize(size)
        positionCards()
        cardsPanel.orderFrontRegardless()
    }
    func positionCards() {
        guard let panel, let cardsPanel, cardsPanel.isVisible || (model.expanded && !model.cards.isEmpty) else { return }
        guard let screen = NSScreen.screens.first(where: { $0.visibleFrame.contains(NSPoint(x: panel.frame.midX, y: panel.frame.midY)) }) ?? NSScreen.main else { return }
        let rect = CardPlacement.frame(pet: panel.frame, cards: cardsPanel.frame.size, screen: screen.visibleFrame)
        cardsPanel.setFrame(rect, display: true)
    }
    func clamp() {
        guard let panel else { return }
        let screen = NSScreen.screens.first { $0.visibleFrame.intersects(panel.frame) } ?? NSScreen.main
        guard let bounds = screen?.visibleFrame else { return }
        let point = PetGeometry.clampedOrigin(panel.frame, scale: model.petScale, screen: bounds)
        if point != panel.frame.origin { panel.setFrameOrigin(point) }
    }
    @objc func didMove() {
        placeStatus()
        UserDefaults.standard.set(panel.frame.origin.x, forKey: "positionX")
        UserDefaults.standard.set(panel.frame.origin.y, forKey: "positionY")
        positionCards()
    }
    func menuItem(_ title: String, _ selector: Selector) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: selector, keyEquivalent: ""); item.target = self; return item
    }
    func buildMenu() {
        let menu = NSMenu()
        let label = NSMenuItem(title: "Claude 橙书娘 · Q版比例修正版 0.3.8", action: nil, keyEquivalent: ""); menu.addItem(label)
        menu.addItem(.separator())
        menu.addItem(menuItem("打开 Claude", #selector(openClaude)))
        menu.addItem(menuItem("活动列表…", #selector(showActivityList)))
        menu.addItem(menuItem("人物大小…", #selector(showAppearanceSettings)))
        menu.addItem(menuItem("显示／隐藏桌宠", #selector(toggleVisible)))
        menu.addItem(menuItem("暂停／恢复观察", #selector(togglePaused)))
        menu.addItem(menuItem("提示音：" + (model.silent ? "关闭" : "开启"), #selector(toggleSound)))
        menu.addItem(.separator())
        menu.addItem(menuItem("连接状态与使用说明…", #selector(showDiagnostics)))
        menu.addItem(menuItem("开启辅助功能设置…", #selector(permissions)))
        menu.addItem(menuItem("打开自定义形象文件夹…", #selector(openSkin)))
        menu.addItem(menuItem("重新加载形象", #selector(reloadSkin)))
        let animationItem = NSMenuItem(title: "预览角色动画", action: nil, keyEquivalent: "")
        let animationMenu = NSMenu()
        for (title, state) in [("待机 / 阅读", "idle"), ("回复 / 工作", "running"), ("等待授权", "waiting"), ("完成 / 挥手", "jumping"), ("查看结果", "review"), ("挥手", "waving"), ("工作轻摆（左）", "running-left"), ("工作轻摆（右）", "running-right"), ("等待表情（仅预览）", "failed")] {
            let item = menuItem(title, #selector(previewState(_:))); item.representedObject = state; animationMenu.addItem(item)
        }
        animationItem.submenu = animationMenu; menu.addItem(animationItem)
        menu.addItem(menuItem("演示：需要授权", #selector(demoApproval)))
        menu.addItem(menuItem("演示：回复结束", #selector(demoDone)))
        menu.addItem(menuItem("清除全部提示", #selector(clearCards)))
        menu.addItem(.separator())
        menu.addItem(menuItem("退出", #selector(quit)))
        statusItem.menu = menu
    }
    @objc func openClaude() { model.openClaude() }
    @objc func toggleVisible() {
        if panel.isVisible { statusPanel.orderOut(nil); cardsPanel.orderOut(nil); panel.orderOut(nil) }
        else { panel.orderFrontRegardless(); resize() }
    }
    @objc func togglePaused() { model.pauseToggle() }
    @objc func toggleSound() { model.silent.toggle(); UserDefaults.standard.set(model.silent, forKey: "silent"); buildMenu() }
    @objc func permissions() { model.permissionSettings() }
    @objc func openSkin() { PetAssets.openCustomDirectory() }
    @objc func reloadSkin() { model.reloadSkin() }
    @objc func previewState(_ sender: NSMenuItem) { if let state = sender.representedObject as? String { model.previewAnimation(state) } }
    @objc func demoApproval() { model.demo(.approval) }
    @objc func demoDone() { model.demo(.completed) }
    @objc func clearCards() { model.clearCards() }
    @objc func quit() { NSApp.terminate(nil) }
    @objc func showDiagnostics() {
        let instructions = """
        Claude Companion · 0.3.8 源码预览版

        Claude Code（桌面 Code 标签页的本地任务）：通过官方 hooks 接收工作、等待授权和本轮结束事件，不依赖辅助功能。手动配置后新开本地 Code 会话；既有会话可能需要重启或在 /hooks 中确认。云端和 SSH 主机不读取这台 Mac 的 hooks，当前不覆盖。
        \(model.codeDiagnostic)
        工作状态优先显示等待授权，其次正在工作的 Code 会话；每个会话独立判断。工作／授权事件30分钟无更新后不再显示，不会猜测已完成。结束事件只表示本轮回复结束。

        以下为原有 Chat/Cowork 窗口观察通道：
        1. 在系统设置 → 隐私与安全性 → 辅助功能，添加并开启本应用。
        2. 打开 Claude，保持一个对话窗口；先用长一点的回复测试。
        3. 观察到生成开始、随后连续两次回到可输入状态，才提示“本轮回复已结束”。
        4. 授权提示需同时识别到允许和拒绝按钮；请在 Claude 中作决定。

        单击角色收起／展开提示，按住角色拖动即可移动，松手后记住位置。右键可调整人物大小；点击铃铛查看本次运行最近20条活动，已读不代表授权已处理。菜单里的演示不代表真实联动。
        标题只取原生窗口标题，无法可靠取名时显示“Claude 当前会话”。会话只按唯一有效的 Chat/Cowork 地址区分；没有可靠地址时暂停事件提醒。
        Chat/Cowork 通道只观察当前可读取的一个窗口。切换会话、最小化或隐藏导致界面不可读时会放弃本轮完成判断；不会猜测。回复结束也可能是你手动停止了生成。
        未验证所有 Claude 版本和控件语言；不保证后台其他会话、云端任务都能提醒。当前不提供桌宠内批准／拒绝。

        隐私：在本机读取 Claude 的按钮标签、会话地址和原生窗口标题，不读取回复内的标题、正文段落或输入内容。不联网、不使用 API Key、不改变 Claude 应用程序文件、不自动授权。Code hooks 丢弃输入中的提示词、工具参数、回复、路径；本地队列仅保存事件类型、会话摘要与时间，读取后删除。活动列表只在内存中。

        形象：公开版使用内置形象，可在菜单中打开预览版的自定义形象文件夹。

        当前诊断（重新打开此窗口刷新）：
        \(model.detail)
        辅助功能权限：\(AXIsProcessTrusted() ? "已开启" : "未开启")
        连接状态：\(model.health.title)
        工作状态：\(model.taskText)
        """
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 560, height: 560))
        let text = NSTextView(frame: scroll.bounds)
        text.isEditable = false; text.isSelectable = true
        text.string = instructions; text.font = .systemFont(ofSize: 13)
        text.textContainerInset = NSSize(width: 20, height: 18)
        text.autoresizingMask = [.width]; text.isVerticallyResizable = true
        text.textContainer?.widthTracksTextView = true
        scroll.documentView = text; scroll.hasVerticalScroller = true
        let window = NSWindow(contentRect: scroll.frame, styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Claude 桌宠 · 连接状态与说明"
        window.contentView = scroll; window.center(); window.isReleasedWhenClosed = false
        diagnosticWindow?.close(); diagnosticWindow = window
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
    }
}

if CommandLine.arguments.contains("--claude-code-hook") {
    CodeHookStore.run()
    exit(0)
}

if CommandLine.arguments.contains("--quit-running") {
    let others = NSRunningApplication.runningApplications(withBundleIdentifier: "com.bakoutaku.claudecompanion.preview")
        .filter { $0.processIdentifier != ProcessInfo.processInfo.processIdentifier }
    for app in others { app.terminate() }
    let deadline = Date().addingTimeInterval(5)
    while others.contains(where: { !$0.isTerminated }) && Date() < deadline {
        RunLoop.current.run(until: Date().addingTimeInterval(0.1))
    }
    exit(others.contains(where: { !$0.isTerminated }) ? 1 : 0)
}

let application = NSApplication.shared
let delegate = AppDelegate()
application.delegate = delegate
application.run()
