import Foundation

public enum SafeModelPath {
    public static func resolve(root: URL, relativePath: String) throws -> URL {
        let pieces = relativePath.split(separator: "/", omittingEmptySubsequences: false)
        guard !pieces.isEmpty, !relativePath.hasPrefix("/"), !relativePath.contains("\\"),
              !pieces.contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }) else { throw ModelCatalogError.invalidManifest }
        try rejectLinks(root)
        var current = root.standardizedFileURL
        for piece in pieces {
            current.appendPathComponent(String(piece))
            try rejectLinks(current)
        }
        guard current.path.hasPrefix(root.standardizedFileURL.path + "/") else { throw ModelCatalogError.invalidManifest }
        return current
    }

    public static func rejectLinks(_ url: URL) throws {
        let path = url.standardizedFileURL.path
        if (try? FileManager.default.destinationOfSymbolicLink(atPath: path)) != nil {
            throw ModelCatalogError.invalidManifest
        }
        guard url.resolvingSymlinksInPath().standardizedFileURL.path == path else { throw ModelCatalogError.invalidManifest }
    }
}
