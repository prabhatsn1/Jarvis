// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "JarvisHUD",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "JarvisHUD",
            path: "Sources/JarvisHUD"
        )
    ]
)
