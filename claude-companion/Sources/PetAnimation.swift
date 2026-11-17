import AppKit
import SwiftUI
import ImageIO

enum PetAssets {
    static var customDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/ClaudeCompanionPreview/Skin", isDirectory: true)
    }
    static func file(_ state: String) -> URL? {
        let chibi = customDirectory.appendingPathComponent("portrait-chibi-v3.png")
        if FileManager.default.fileExists(atPath: chibi.path) { return chibi }
        let portrait = customDirectory.appendingPathComponent("portrait-v2.png")
        if FileManager.default.fileExists(atPath: portrait.path) { return portrait }
        let custom = customDirectory.appendingPathComponent(state + ".gif")
        if FileManager.default.fileExists(atPath: custom.path) { return custom }
        if let chibi = Bundle.main.url(forResource: "portrait-chibi-v3", withExtension: "png", subdirectory: "ClaudeOrangeScholar") { return chibi }
        if let portrait = Bundle.main.url(forResource: "portrait-v2", withExtension: "png", subdirectory: "ClaudeOrangeScholar") { return portrait }
        if let bundled = Bundle.main.url(forResource: state, withExtension: "gif", subdirectory: "ClaudeOrangeScholar") { return bundled }
        for ext in ["webp", "png"] {
            let atlas = customDirectory.appendingPathComponent("spritesheet." + ext)
            if FileManager.default.fileExists(atPath: atlas.path) { return atlas }
        }
        return Bundle.main.url(forResource: "spritesheet", withExtension: "webp", subdirectory: "ClaudeOrangeScholar")
    }
    /// Conservative union across every animation frame, including custom skins.
    static func horizontalInsets() -> (CGFloat, CGFloat) {
        var left: CGFloat = 1, right: CGFloat = 1
        for state in AnimationClip.rows.keys {
            guard let url = file(state), let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return (0, 0) }
            let frames: [CGImage]
            if url.pathExtension == "gif" {
                frames = (0..<CGImageSourceGetCount(source)).compactMap { CGImageSourceCreateImageAtIndex(source, $0, nil) }
            } else if let image = CGImageSourceCreateImageAtIndex(source, 0, nil) {
                frames = AnimationClip.skin(image, filename: url.lastPathComponent, state: state)?.frames ?? []
            } else { return (0, 0) }
            guard !frames.isEmpty else { return (0, 0) }
            for image in frames {
                let w = image.width, h = image.height
                var pixels = [UInt8](repeating: 0, count: w * h * 4)
                pixels.withUnsafeMutableBytes { buffer in
                    let ctx = CGContext(data: buffer.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                    ctx.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
                }
                var x0 = w, x1 = 0
                for y in 0..<h { for x in 0..<w where pixels[(y * w + x) * 4 + 3] > 8 { x0 = min(x0, x); x1 = max(x1, x + 1) } }
                guard x1 > x0 else { return (0, 0) }
                // Reserve 4pt for the working animation's subtle sway.
                left = min(left, max(0, CGFloat(x0) / CGFloat(w) - 4 / 150))
                right = min(right, max(0, CGFloat(w - x1) / CGFloat(w) - 4 / 150))
            }
        }
        return (left, right)
    }
    static func openCustomDirectory() {
        do {
            try FileManager.default.createDirectory(at: customDirectory, withIntermediateDirectories: true)
            let guide = customDirectory.appendingPathComponent("使用说明.txt")
            if !FileManager.default.fileExists(atPath: guide.path) {
                try localized("自定义桌宠形象：放入透明背景 GIF 后，从桌宠菜单选择「重新加载形象」。\n支持文件：idle.gif（待机）、running.gif（回复）、waiting.gif（授权）、jumping.gif（结束）、review.gif（查看结果）。\n建议每张使用相同尺寸与角色大小，比例约192×208；建议单文件不超过10MB。未提供的状态继续使用内置形象。\n此目录在应用外部，替换 GIF 无需修改程序、重新签名或重新授权辅助功能。\n内置橙书娘素材来自 fywdy/chatgpt-chibi-pets，CC BY-NC 4.0，非商业使用并保留署名。\n").write(to: guide, atomically: true, encoding: .utf8)
            }
            NSWorkspace.shared.open(customDirectory)
        } catch {
            let alert = NSAlert(); alert.messageText = localized("无法打开形象文件夹"); alert.informativeText = error.localizedDescription; alert.runModal()
        }
    }
}

struct AnimationClip {
    let frames: [CGImage]
    let seconds: [Double]
    static let rows: [String: (Int, [Double])] = [
        "idle": (0, [0.28, 0.11, 0.11, 0.14, 0.14, 0.32]),
        "running-right": (1, [0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.22]),
        "running-left": (2, [0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.12, 0.22]),
        "waving": (3, [0.14, 0.14, 0.14, 0.28]),
        "jumping": (4, [0.14, 0.14, 0.14, 0.14, 0.28]),
        "failed": (5, [0.14, 0.14, 0.14, 0.14, 0.14, 0.14, 0.14, 0.24]),
        "waiting": (6, [0.15, 0.15, 0.15, 0.15, 0.15, 0.26]),
        "running": (7, [0.12, 0.12, 0.12, 0.12, 0.12, 0.22]),
        "review": (8, [0.15, 0.15, 0.15, 0.15, 0.15, 0.28])
    ]
    static func skin(_ image: CGImage, filename: String, state: String) -> AnimationClip? {
        if filename == "portrait-chibi-v3.png" { return chibi(image, state: state) }
        if filename == "portrait-v2.png" { return portraits(image, state: state) }
        return atlas(image, state: state)
    }
    /// The user-selected atlas has irregular gutters. Extract its actual cells,
    /// keeping the original pixels and proportions, then align centers and feet.
    static func chibi(_ image: CGImage, state: String) -> AnimationClip? {
        guard image.width == 1254, image.height == 1254 else { return nil }
        let xs = [0, 340, 625, 915, 1254], ys = [0, 313, 625, 935, 1254]
        let row: Int
        switch state {
        case "running", "running-left", "running-right", "review": row = 1
        case "waiting", "failed": row = 2
        case "jumping", "waving": row = 3
        default: row = 0
        }
        let frames = (0..<4).compactMap { column -> CGImage? in
            guard let frame = image.cropping(to: CGRect(x: xs[column], y: ys[row], width: xs[column + 1] - xs[column], height: ys[row + 1] - ys[row])) else { return nil }
            let w = frame.width, h = frame.height
            var pixels = [UInt8](repeating: 0, count: w * h * 4)
            pixels.withUnsafeMutableBytes { buffer in
                let ctx = CGContext(data: buffer.baseAddress, width: w, height: h, bitsPerComponent: 8, bytesPerRow: w * 4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
                ctx.draw(frame, in: CGRect(x: 0, y: 0, width: w, height: h))
            }
            var x0 = w, x1 = 0, y1 = 0
            for y in 0..<h { for x in 0..<w where pixels[(y * w + x) * 4 + 3] > 127 {
                x0 = min(x0, x); x1 = max(x1, x + 1); y1 = max(y1, y + 1)
            } }
            guard x1 > x0, let canvas = CGContext(data: nil, width: 384, height: 416, bitsPerComponent: 8, bytesPerRow: 384 * 4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
            canvas.interpolationQuality = .none
            canvas.draw(frame, in: CGRect(x: 192 - CGFloat(x0 + x1) / 2, y: CGFloat(350 - y1), width: CGFloat(w), height: CGFloat(h)))
            return canvas.makeImage()
        }
        guard frames.count == 4 else { return nil }
        let timings = row == 0 ? [1.1, 0.12, 0.16, 1.1] : [0.45, 0.45, 0.3, 0.45]
        return AnimationClip(frames: frames, seconds: timings)
    }
    static func portraits(_ image: CGImage, state: String) -> AnimationClip? {
        guard image.width == image.height, image.width >= 1024 else { return nil }
        let cell = image.width / 2
        let index: Int
        switch state {
        case "running", "running-left", "running-right", "review": index = 1
        case "waiting", "failed": index = 2
        case "jumping", "waving": index = 3
        default: index = 0
        }
        guard let frame = image.cropping(to: CGRect(x: (index % 2) * cell, y: (index / 2) * cell, width: cell, height: cell)) else { return nil }
        return AnimationClip(frames: [frame], seconds: [0.08])
    }
    static func atlas(_ image: CGImage, state: String) -> AnimationClip? {
        guard image.width == 1536, image.height == 2288 || image.height == 1872,
              let (row, timings) = rows[state] else { return nil }
        let frames = timings.indices.compactMap { image.cropping(to: CGRect(x: $0 * 192, y: row * 208, width: 192, height: 208)) }
        guard frames.count == timings.count else { return nil }
        return AnimationClip(frames: frames, seconds: timings)
    }
}

/// Draw CGImage frames directly so the atlas alpha channel survives animation playback.
final class PetImageCanvas: NSView {
    override var isOpaque: Bool { false }
    override var intrinsicContentSize: NSSize { NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric) }
    private var clip: AnimationClip?
    private var index = 0
    private var key = ""
    private var atlasKey = ""
    private var atlasImage: CGImage?
    private var timer: Timer?
    private var paused = false
    private var working = false
    private var motionPhase = 0.0
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true; layer?.backgroundColor = NSColor.clear.cgColor
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    deinit { timer?.invalidate() }
    func configure(state: String, epoch: Int, paused: Bool) {
        working = state == "running" || state == "running-left" || state == "running-right"
        let url = PetAssets.file(state)
        let newKey = (url?.path ?? "missing") + ":\(epoch):" + state
        if newKey != key {
            key = newKey; timer?.invalidate(); timer = nil; index = 0; clip = nil
            if let url, let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
               let size = attrs[.size] as? NSNumber, size.intValue <= 20 * 1024 * 1024 {
                if url.pathExtension.lowercased() == "gif", let source = CGImageSourceCreateWithURL(url as CFURL, nil) {
                    let frames = (0..<CGImageSourceGetCount(source)).compactMap { CGImageSourceCreateImageAtIndex(source, $0, nil) }
                    if !frames.isEmpty {
                        let timings = frames.indices.map { i -> Double in
                            let p = CGImageSourceCopyPropertiesAtIndex(source, i, nil) as? [CFString: Any]
                            let gif = p?[kCGImagePropertyGIFDictionary] as? [CFString: Any]
                            return max(0.04, (gif?[kCGImagePropertyGIFUnclampedDelayTime] as? Double) ?? (gif?[kCGImagePropertyGIFDelayTime] as? Double) ?? 0.15)
                        }
                        clip = AnimationClip(frames: frames, seconds: timings)
                    }
                } else {
                    let sourceKey = url.path + ":\(epoch)"
                    if sourceKey != atlasKey {
                        atlasKey = sourceKey
                        atlasImage = CGImageSourceCreateWithURL(url as CFURL, nil).flatMap { CGImageSourceCreateImageAtIndex($0, 0, nil) }
                    }
                    if let image = atlasImage { clip = AnimationClip.skin(image, filename: url.lastPathComponent, state: state) }
                }
            }
            needsDisplay = true
        }
        if self.paused != paused { needsDisplay = true }
        self.paused = paused
        if paused { timer?.invalidate(); timer = nil }
        else if timer == nil { schedule() }
    }
    private func schedule() {
        guard !paused, let clip, (clip.frames.count > 1 || working) else { return }
        let next = Timer(timeInterval: clip.seconds[index], repeats: false) { [weak self] _ in
            guard let self, let clip = self.clip else { return }
            self.motionPhase += 0.18
            self.timer = nil; self.index = (self.index + 1) % clip.frames.count
            self.needsDisplay = true; self.schedule()
        }
        timer = next; RunLoop.main.add(next, forMode: .common)
    }
    override func draw(_ dirtyRect: NSRect) {
        guard let context = NSGraphicsContext.current?.cgContext else { return }
        context.clear(bounds)
        guard let clip, clip.frames.indices.contains(index) else { return }
        context.saveGState()
        if working && !paused && clip.frames.count == 1 {
            context.translateBy(x: bounds.midX + sin(motionPhase) * 1.5, y: bounds.midY + sin(motionPhase * 2) * 1.0)
            context.rotate(by: sin(motionPhase) * 0.012)
            context.translateBy(x: -bounds.midX, y: -bounds.midY)
        }
        Self.render(clip.frames[index], in: context, bounds: bounds)
        context.restoreGState()
    }
    static func render(_ image: CGImage, in context: CGContext, bounds: CGRect) {
        let scale = min(bounds.width / CGFloat(image.width), bounds.height / CGFloat(image.height))
        let width = CGFloat(image.width) * scale, height = CGFloat(image.height) * scale
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: (bounds.width - width) / 2, y: (bounds.height - height) / 2, width: width, height: height))
    }
}

struct AnimatedPet: NSViewRepresentable {
    var state: String
    var epoch: Int
    var paused: Bool
    func makeNSView(context: Context) -> PetImageCanvas { PetImageCanvas(frame: .zero) }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: PetImageCanvas, context: Context) -> CGSize? {
        CGSize(width: proposal.width ?? 150, height: proposal.height ?? 170)
    }
    func updateNSView(_ view: PetImageCanvas, context: Context) {
        view.configure(state: state, epoch: epoch, paused: paused)
        view.setAccessibilityLabel(localized("Claude 橙书娘 Q 版 · ") + state)
    }
}
