import AppKit
import SwiftUI

class HUDPanel: NSPanel {
    init(stateManager: StateManager) {
        super.init(
            contentRect: NSRect(x: 0, y: 0, width: 200, height: 200),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        // Floating, always-on-top, transparent
        self.level = .floating
        self.isOpaque = false
        self.backgroundColor = .clear
        self.hasShadow = false
        self.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        self.isMovableByWindowBackground = true
        self.ignoresMouseEvents = false

        let orbView = OrbView(stateManager: stateManager)
        self.contentView = NSHostingView(rootView: orbView)
    }

    func show() {
        guard let screen = NSScreen.main else {
            orderFrontRegardless()
            return
        }
        let frame = screen.visibleFrame
        let x = frame.midX - self.frame.width / 2
        let y = frame.minY + 60
        setFrameOrigin(NSPoint(x: x, y: y))
        orderFrontRegardless()
    }

    // Don't steal focus from other apps
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}
