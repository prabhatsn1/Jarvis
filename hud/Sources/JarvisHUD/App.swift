import SwiftUI

@main
struct JarvisHUDApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        // No window — HUD is managed by AppDelegate
        Settings { EmptyView() }
    }
}
