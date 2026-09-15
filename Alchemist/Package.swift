// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Alchemist",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "Alchemist", targets: ["Alchemist"])
    ],
    targets: [
        .executableTarget(
            name: "Alchemist",
            path: "Sources/Alchemist",
            linkerSettings: [
                .linkedFramework("AVFoundation"),
                .linkedFramework("VideoToolbox"),
                .linkedFramework("CoreMedia"),
                .linkedFramework("CoreVideo"),
                .linkedFramework("AppKit")
            ]
        )
    ],
    swiftLanguageModes: [.v5]
)
