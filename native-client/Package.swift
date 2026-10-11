// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "Deepdesk",
    platforms: [.macOS("26.4")],
    products: [
        .executable(name: "Deepdesk", targets: ["Deepdesk"]),
        .library(name: "DeepdeskCore", targets: ["DeepdeskCore"])
    ],
    targets: [
        .target(name: "DeepdeskCore"),
        .executableTarget(name: "Deepdesk", dependencies: ["DeepdeskCore"], resources: [.copy("Resources/model-catalog.json")]),
        .testTarget(name: "DeepdeskCoreTests", dependencies: ["DeepdeskCore"], resources: [.copy("Fixtures/model-catalog.json")])
    ]
)
