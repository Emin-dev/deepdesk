import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

/// A loopback origin built from a port, never from an arbitrary user-supplied URL.
public struct LocalEndpoint: Hashable, Sendable {
    public let port: Int

    public init(port: Int = 5000) throws {
        guard (1...65535).contains(port) else { throw APIError.invalidPort }
        self.port = port
    }

    public var baseURL: URL { URL(string: "http://127.0.0.1:\(port)")! }

    public func url(path: String) throws -> URL {
        guard path.hasPrefix("/"), !path.hasPrefix("//"),
              !path.contains("\\"), !path.contains("#"), !path.contains("?") else {
            throw APIError.invalidPath
        }
        guard var parts = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidPath
        }
        parts.path = path
        guard let url = parts.url, url.host == "127.0.0.1", url.port == port else {
            throw APIError.invalidPath
        }
        return url
    }
}

public struct HTTPResponse: Sendable {
    public let data: Data
    public let status: Int
    public let contentType: String?
    public let headers: [String: String]
    public init(data: Data, status: Int, contentType: String? = "application/json", headers: [String: String] = [:]) {
        self.data = data
        self.status = status
        self.contentType = contentType
        self.headers = headers
    }
    public func header(_ name: String) -> String? {
        headers.first { $0.key.caseInsensitiveCompare(name) == .orderedSame }?.value
    }
}

public protocol HTTPTransport: Sendable {
    func send(_ request: URLRequest) async throws -> HTTPResponse
    func invalidate() async
}

/// Rejects every redirect: a local service must never redirect credentials or requests off-device.
private final class NoRedirectDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

public final class EphemeralHTTPTransport: HTTPTransport, @unchecked Sendable {
    private let session: URLSession
    private let delegate: NoRedirectDelegate

    public init() {
        let redirectDelegate = NoRedirectDelegate()
        self.delegate = redirectDelegate
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.urlCredentialStorage = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 60
        configuration.httpShouldSetCookies = true
        #if os(macOS)
        // The local API must not travel through a system HTTP proxy.
        configuration.connectionProxyDictionary = [:]
        #endif
        session = URLSession(configuration: configuration, delegate: redirectDelegate, delegateQueue: nil)
    }

    public func send(_ request: URLRequest) async throws -> HTTPResponse {
        guard let url = request.url, url.scheme == "http", url.host == "127.0.0.1",
              url.user == nil, url.password == nil else { throw APIError.nonLocalRequest }
        do {
            let (data, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
            guard data.count <= 32 * 1024 * 1024 else { throw APIError.responseTooLarge }
            return HTTPResponse(data: data, status: http.statusCode,
                                contentType: http.value(forHTTPHeaderField: "Content-Type"),
                                headers: http.allHeaderFields.reduce(into: [:]) { result, entry in
                                    if let key = entry.key as? String, let value = entry.value as? String { result[key] = value }
                                })
        } catch is CancellationError {
            throw CancellationError()
        } catch let error as APIError {
            throw error
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            // Deliberately omit response bodies, URLs with parameters, and credentials from errors.
            throw APIError.connectionUnavailable
        }
    }

    public func invalidate() async { session.invalidateAndCancel() }
}

public enum APIError: Error, LocalizedError, Equatable, Sendable {
    case invalidPort, invalidPath, nonLocalRequest, invalidResponse, responseTooLarge
    case connectionUnavailable, unauthorized, rejectedCredentials, csrfExpired, instanceMismatch
    case server(status: Int, message: String)
    case invalidInput(String)

    public var errorDescription: String? {
        switch self {
        case .invalidPort: "Enter a port between 1 and 65535."
        case .invalidPath: "The local API path is invalid."
        case .nonLocalRequest: "Deepdesk only connects to the local engine at 127.0.0.1."
        case .invalidResponse: "The local engine returned an unexpected response. Check that its version matches Deepdesk."
        case .responseTooLarge: "This response is too large to display in Deepdesk."
        case .connectionUnavailable: "The local research engine is unavailable. Retry local startup to reconnect. Your saved research remains on this Mac."
        case .unauthorized: "Your local session ended. Sign in again to continue."
        case .instanceMismatch: "The local engine identity changed. Restart the bundled engine before signing in again."
        case .rejectedCredentials: "The local engine did not accept that username and password."
        case .csrfExpired: "The security token expired. Sign in again before retrying."
        case .server(let status, let message): "Local engine (\(status)): \(message)"
        case .invalidInput(let message): message
        }
    }
}

public enum FormEncoding {
    public static func encode(_ fields: [String: String]) -> Data {
        let safe = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~")
        let text = fields.keys.sorted().map { key in
            let name = key.addingPercentEncoding(withAllowedCharacters: safe) ?? ""
            let value = fields[key]!.addingPercentEncoding(withAllowedCharacters: safe) ?? ""
            return "\(name)=\(value)"
        }.joined(separator: "&")
        return Data(text.utf8)
    }
}
