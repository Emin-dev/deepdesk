import Foundation

public struct CuratedModel: Decodable, Identifiable, Sendable, Equatable {
    public let id: String
    public let name: String
    public let summary: String
    public let repository: String
    public let revision: String
    public let targetDirectory: String
    public let draftDirectory: String
    public let contentWarning: String?
    public let runtime: String
    public let minimumMemoryGB: Int
    public let thinkingSupported: Bool
    public let licenseName: String
    public let licenseURL: URL
    public let artifacts: [ModelArtifact]
    public let downloadHosts: [String]
    public var totalBytes: Int64 { artifacts.reduce(0) { $0 + $1.bytes } }
}

public struct ModelArtifact: Decodable, Sendable, Equatable {
    public let path: String
    public let url: URL
    public let sha256: String
    public let bytes: Int64
}

public struct ModelCatalog: Decodable, Sendable {
    public let version: Int
    public let models: [CuratedModel]

    public func validated() throws -> ModelCatalog {
        guard version == 1, models.count <= 16, Set(models.map(\.id)).count == models.count else { throw ModelCatalogError.invalidManifest }
        let idCharacters = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789-_")
        let hex = CharacterSet(charactersIn: "0123456789abcdef")
        for model in models {
            guard !model.id.isEmpty, model.id.unicodeScalars.allSatisfy(idCharacters.contains),
                  !model.artifacts.isEmpty, model.artifacts.count <= 256, model.minimumMemoryGB > 0,
                  !model.targetDirectory.isEmpty, model.targetDirectory.unicodeScalars.allSatisfy(idCharacters.contains),
                  !model.draftDirectory.isEmpty, model.draftDirectory.unicodeScalars.allSatisfy(idCharacters.contains),
                  model.revision.count == 40, model.revision.unicodeScalars.allSatisfy(hex.contains),
                  !model.downloadHosts.isEmpty, Set(model.downloadHosts).isSubset(of: ["huggingface.co", "us.aws.cdn.hf.co"]), model.licenseURL.scheme == "https" else { throw ModelCatalogError.invalidManifest }
            var seen = Set<String>()
            for artifact in model.artifacts {
                let pieces = artifact.path.split(separator: "/", omittingEmptySubsequences: false)
                guard !pieces.isEmpty, !pieces.contains(where: { $0.isEmpty || $0 == "." || $0 == ".." }),
                      !artifact.path.contains("\\"), !artifact.path.hasPrefix("/"),
                      seen.insert(artifact.path).inserted, artifact.bytes > 0, artifact.bytes <= 64 * 1024 * 1024 * 1024,
                      ["json", "safetensors", "jinja", "md"].contains(URL(fileURLWithPath: artifact.path).pathExtension.lowercased()),
                      artifact.sha256.count == 64, artifact.sha256.unicodeScalars.allSatisfy(hex.contains),
                      artifact.url.scheme == "https", artifact.url.user == nil, artifact.url.password == nil,
                      artifact.url.port == nil, artifact.url.host == "huggingface.co",
                      artifact.url.path.range(of: "/resolve/[a-f0-9]{40}/", options: .regularExpression) != nil,
                      let host = artifact.url.host,
                      model.downloadHosts.contains(host.lowercased()) else { throw ModelCatalogError.invalidManifest }
            }
        }
        return self
    }
}

public enum ModelCatalogError: Error, LocalizedError, Sendable {
    case invalidManifest, notBundled, insufficientDiskSpace, hashMismatch, downloadFailed, invalidRedirect, runtimeUnavailable
    public var errorDescription: String? {
        switch self {
        case .invalidManifest: "The bundled model catalog failed validation. No model was downloaded."
        case .notBundled: "This build has no verified model catalog yet. Install a complete build before downloading a model."
        case .insufficientDiskSpace: "There is not enough free disk space for this model and its temporary download."
        case .hashMismatch: "The downloaded model failed its integrity check. It was not installed."
        case .downloadFailed: "The model download was interrupted. Try again when your connection is available."
        case .invalidRedirect: "The model download was redirected to an unapproved host. It was stopped."
        case .runtimeUnavailable: "This build does not include the inference runtime required by this model."
        }
    }
}
