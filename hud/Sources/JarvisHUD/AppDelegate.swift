import AppKit

class AppDelegate: NSObject, NSApplicationDelegate {
    var hudPanel: HUDPanel?
    var stateManager: StateManager?
    var ipcClient: IPCClient?
    var statusItem: NSStatusItem?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Hide dock icon — Jarvis lives in the menu bar
        NSApp.setActivationPolicy(.accessory)

        stateManager = StateManager()

        hudPanel = HUDPanel(stateManager: stateManager!)
        hudPanel?.show()

        ipcClient = IPCClient(stateManager: stateManager!)
        ipcClient?.connect()

        setupStatusBar()
    }

    private func setupStatusBar() {
        statusItem = NSStatusBar.system.statusItem(
            withLength: NSStatusItem.squareLength
        )
        if let button = statusItem?.button {
            button.image = NSImage(
                systemSymbolName: "circle.fill",
                accessibilityDescription: "Jarvis"
            )
            button.action = #selector(toggleHUD)
            button.target = self
        }
    }

    @objc private func toggleHUD() {
        if hudPanel?.isVisible == true {
            hudPanel?.orderOut(nil)
        } else {
            hudPanel?.show()
        }
    }
}
