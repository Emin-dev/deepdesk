import Foundation

public enum DownloadResponseAction: Equatable, Sendable { case restart, resume }
public enum DownloadResponsePolicy {
    public static func validate(status: Int, offset: Int64, total: Int64,
                                expectedETag: String?, responseETag: String?, contentRange: String?) throws -> DownloadResponseAction {
        guard total > 0, offset >= 0, offset < total else { throw ModelCatalogError.downloadFailed }
        if status == 200 { return .restart }
        guard status == 206, offset > 0,
              let expectedETag, !expectedETag.isEmpty, !expectedETag.hasPrefix("W/"),
              responseETag == expectedETag,
              contentRange == "bytes \(offset)-\(total - 1)/\(total)" else { throw ModelCatalogError.downloadFailed }
        return .resume
    }

    public static func acceptsRedirect(_ url: URL, allowedHosts: Set<String>) -> Bool {
        url.scheme == "https" && url.user == nil && url.password == nil &&
        (url.port == nil || url.port == 443) && allowedHosts.contains(url.host?.lowercased() ?? "")
    }
}
