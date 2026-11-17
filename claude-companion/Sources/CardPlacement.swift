import Foundation
import CoreGraphics

enum CardPlacement {
    /// Position only the notification surface. Its anchor (the pet) is immutable.
    static func frame(pet: CGRect, cards: CGSize, screen: CGRect) -> CGRect {
        let width = min(cards.width, screen.width)
        let height = min(cards.height, screen.height)
        var x = pet.maxX - width
        var y = pet.maxY + 6
        if y + height > screen.maxY {
            if pet.minY - height - 6 >= screen.minY {
                y = pet.minY - height - 6
            } else {
                x = pet.minX - width - 6
                if x < screen.minX { x = pet.maxX + 6 }
                y = pet.midY - height / 2
            }
        }
        x = max(screen.minX, min(x, screen.maxX - width))
        y = max(screen.minY, min(y, screen.maxY - height))
        return CGRect(x: x, y: y, width: width, height: height)
    }
}
