// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Deepdesk",
    platforms: [.macOS("26.4")],
    products: [
        .executable(name: "Deepdesk", targets: ["Deepdesk"]),
        .library(name: "DeepdeskCore", targets: ["DeepdeskCore"]),
        .executable(name: "DeepdeskResourceSmoke", targets: ["DeepdeskResourceSmoke"])
    ],
    targets: [
        .target(name: "DeepdeskCore"),
        .executableTarget(name: "DeepdeskResourceSmoke", dependencies: ["DeepdeskCore"], path: "Tools/ResourceSmoke"),
        .executableTarget(name: "Deepdesk", dependencies: ["DeepdeskCore"], resources: [.copy("Resources/model-catalog.json")]),
        .testTarget(name: "DeepdeskCoreTests", dependencies: ["DeepdeskCore"], resources: [.copy("Fixtures/model-catalog.json")])
    ]
)
