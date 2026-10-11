import Foundation
import DeepdeskCore
import Darwin

// CI-only command-line probe. It does not initialize the app, identity, network, or runtime supervisors.
guard CommandLine.arguments.count == 2 else {
    print("DEEPDESK_RESOURCE_SMOKE invalid-arguments")
    exit(64)
}
do {
    let catalog = try BundledModelCatalog.load(
        applicationBundleURL: URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
    )
    guard catalog.models.map(\.id) == ["qwen38-27b-splash", "qwen38-27b-uncensored"] else {
        throw ModelCatalogError.invalidManifest
    }
    print("DEEPDESK_RESOURCE_SMOKE catalog-ok models=2 default=qwen38-27b-splash")
} catch {
    // Deliberately omit arbitrary paths or malformed resource contents from CI logs.
    print("DEEPDESK_RESOURCE_SMOKE catalog-unavailable")
    exit(2)
}
