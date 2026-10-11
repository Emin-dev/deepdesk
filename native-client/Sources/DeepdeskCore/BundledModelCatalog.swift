import Foundation

/// The installed app has one catalog location, independent of SwiftPM's build directory.
/// Never call the generated Bundle.module accessor here: its fallback can mask a broken app bundle.
public enum BundledModelCatalog {
    public static let resourceBundleName = "Deepdesk_Deepdesk.bundle"
    public static let maximumBytes = 1_048_576

    public static func load(applicationBundleURL: URL) throws -> ModelCatalog {
        guard applicationBundleURL.isFileURL, applicationBundleURL.pathExtension == "app" else {
            throw ModelCatalogError.notBundled
        }
        let app = applicationBundleURL.standardizedFileURL
        let bundleURL = try SafeModelPath.resolve(
            root: app, relativePath: "Contents/Resources/\(resourceBundleName)"
        )
        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: bundleURL.path, isDirectory: &isDirectory),
              isDirectory.boolValue,
              let resources = Bundle(url: bundleURL),
              let catalogURL = resources.url(forResource: "model-catalog", withExtension: "json"),
              catalogURL.standardizedFileURL.path.hasPrefix(bundleURL.path + "/") else {
            throw ModelCatalogError.notBundled
        }
        let data = try SafeLocalFile.read(catalogURL, maximumBytes: maximumBytes)
        let catalog = try JSONDecoder().decode(ModelCatalog.self, from: data).validated()
        guard !catalog.models.isEmpty else { throw ModelCatalogError.invalidManifest }
        return catalog
    }
}
