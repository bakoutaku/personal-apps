import Foundation
import CoreGraphics

enum PetGeometry {
    static var artInsets: (left: CGFloat, right: CGFloat) = (13 / 192, 13 / 192)
    static func normalized(_ scale: Double) -> Double {
        scale.isFinite ? min(1.6, max(0.6, scale)) : 1
    }
    static func size(scale: Double) -> CGSize {
        let s = normalized(scale)
        return CGSize(width: max(150, 150 * s) + 22, height: 170 * s + 40)
    }
    /// Actual skin alpha margins, plus view padding and centering below scale 1.
    static func clearInsets(scale: Double) -> (left: CGFloat, right: CGFloat) {
        let s = normalized(scale)
        let art = 150 * s
        let slack = (size(scale: s).width - 22 - art) / 2
        return (8 + slack + art * artInsets.left, 14 + slack + art * artInsets.right)
    }
    /// Lets the transparent margins hang off the screen so the visible pet can
    /// sit as close to a side edge as other desktop pets do.
    static func clampedOrigin(_ frame: CGRect, scale: Double, screen: CGRect) -> CGPoint {
        let insets = clearInsets(scale: scale)
        let x = max(screen.minX - insets.left, min(frame.minX, screen.maxX - frame.width + insets.right))
        let y = max(screen.minY, min(frame.minY, screen.maxY - frame.height))
        return CGPoint(x: x, y: y)
    }
    /// Scaling keeps the bottom center anchored; notification changes never call this.
    static func scaledFrame(_ frame: CGRect, scale: Double, screen: CGRect) -> CGRect {
        let size = size(scale: scale)
        let centered = CGRect(x: frame.midX - size.width / 2, y: frame.minY, width: size.width, height: size.height)
        return CGRect(origin: clampedOrigin(centered, scale: scale, screen: screen), size: size)
    }
}
