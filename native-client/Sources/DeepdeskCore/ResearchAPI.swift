import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public actor ResearchAPI {
    public let endpoint: LocalEndpoint
    private let transport: any HTTPTransport
    private let expectedInstance: String?
    private var csrfToken: String?
    private var authContext: String?
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    public init(endpoint: LocalEndpoint, transport: any HTTPTransport = EphemeralHTTPTransport(), expectedInstance: String? = nil) {
        self.endpoint = endpoint
        self.transport = transport
        self.expectedInstance = expectedInstance
    }

    public func checkAuthentication() async throws -> AuthState {
        let response = try await send(path: "/auth/check")
        if response.status == 401 { return AuthState(authenticated: false, username: nil) }
        return try decode(AuthState.self, response)
    }

    public func signIn(username: String, password: String) async throws -> AuthState {
        guard !username.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !password.isEmpty else {
            throw APIError.invalidInput("Enter your local username and password.")
        }
        try await refreshCSRF()
        let response = try await send(path: "/auth/login", method: "POST",
                                      body: FormEncoding.encode(["username": username, "password": password, "remember": "false"]),
                                      contentType: "application/x-www-form-urlencoded", mutation: true)
        if response.status == 401 { throw APIError.rejectedCredentials }
        guard response.status == 302 || response.status == 200 else {
            throw error(for: response)
        }
        let state = try await checkAuthentication()
        guard state.authenticated else { throw APIError.rejectedCredentials }
        // Upstream login clears and rotates the session: the pre-login CSRF token is invalid.
        csrfToken = nil
        authContext = nil
        try await refreshCSRF()
        return state
    }

    public func register(username: String, password: String, confirmation: String,
                         acknowledgedNoRecovery: Bool) async throws -> AuthState {
        guard username.count >= 3, !password.isEmpty, password == confirmation, acknowledgedNoRecovery else {
            throw APIError.invalidInput("Use a username of at least 3 characters, matching passwords, and acknowledge that a lost password cannot be recovered.")
        }
        try await refreshCSRF()
        let response = try await send(path: "/auth/register", method: "POST",
                                      body: FormEncoding.encode(["username": username, "password": password,
                                                                 "confirm_password": confirmation, "acknowledge": "true"]),
                                      contentType: "application/x-www-form-urlencoded", mutation: true)
        guard response.status == 302 || response.status == 200 else {
            if response.status == 400 {
                throw APIError.invalidInput("Account creation was not accepted. Use letters, numbers, _ or - in the username and a strong password. That username may already exist.")
            }
            if response.status >= 500 {
                throw APIError.invalidInput("Account setup was interrupted. The account may already exist; try signing in before attempting to create it again.")
            }
            throw error(for: response)
        }
        let state = try await checkAuthentication()
        guard state.authenticated else {
            throw APIError.invalidInput("The account may have been created, but sign-in was not completed. Try signing in.")
        }
        csrfToken = nil
        authContext = nil
        try await refreshCSRF()
        return state
    }

    public func signOut() async throws {
        let response = try await send(path: "/auth/logout", method: "POST", mutation: true)
        guard (200...299).contains(response.status) || response.status == 302 else { throw error(for: response) }
        await disconnect()
    }

    public func disconnect() async {
        csrfToken = nil
        authContext = nil
        await transport.invalidate()
    }

    public func start(_ request: ResearchStartRequest) async throws -> ResearchAccepted {
        let count = request.query.trimmingCharacters(in: .whitespacesAndNewlines).count
        guard count > 0 && count <= 10_000 else {
            throw APIError.invalidInput("Enter a research question of 1 to 10,000 characters.")
        }
        let response = try await send(path: "/api/start_research", method: "POST",
                                      body: encoder.encode(request), mutation: true)
        // Never retry this mutation automatically: a lost response may still have started a job.
        let accepted = try decode(ResearchAccepted.self, response)
        guard ["success", "queued"].contains(accepted.status) else { throw APIError.invalidResponse }
        try validateID(accepted.researchID)
        return accepted
    }

    public func progress(id: String) async throws -> ResearchProgress {
        try validateID(id)
        return try decode(ResearchProgress.self, await send(path: "/api/research/\(id)/status"))
    }

    public func stop(id: String) async throws {
        try validateID(id)
        let response = try await send(path: "/api/terminate/\(id)", method: "POST", mutation: true)
        try validateSuccess(response)
        let payload = try decoder.decode(JSONValue.self, from: response.data)
        guard payload["status"]?.string == "success" else { throw APIError.invalidResponse }
    }

    public func report(id: String) async throws -> ResearchReport {
        try validateID(id)
        return try decode(ResearchReport.self, await send(path: "/api/report/\(id)"))
    }

    public func history(offset: Int = 0) async throws -> [ResearchHistoryItem] {
        let response = try await send(path: "/history/api", query: [
            URLQueryItem(name: "limit", value: "50"), URLQueryItem(name: "offset", value: "\(max(0, offset))")
        ])
        let history = try decode(HistoryResponse.self, response)
        guard history.status == "success" else { throw APIError.invalidResponse }
        return history.items
    }

    public func settings() async throws -> EngineSettings {
        var result: [String: SettingMetadata] = [:]
        for key in SettingsKey.readable {
            result[key] = try await setting(key: key)
        }
        return EngineSettings(values: result)
    }

    public func availableModels() async throws -> AvailableModels {
        // Explicit user action only; discovery can contact configured model services.
        try decode(AvailableModels.self, await send(path: "/settings/api/available-models"))
    }

    public func setting(key: String) async throws -> SettingMetadata {
        guard SettingsKey.readable.contains(key) else { throw APIError.invalidInput("This setting is not exposed by Deepdesk.") }
        return try decode(SettingMetadata.self, await send(path: "/settings/api/\(key)"))
    }

    public func updateSetting(key: String, value: String) async throws -> SettingMetadata {
        guard SettingsKey.writable.contains(key) else { throw APIError.invalidInput("This setting cannot be changed in Deepdesk.") }
        let body = try encoder.encode(["value": value])
        let response = try await send(path: "/settings/api/\(key)", method: "PUT", body: body, mutation: true)
        try validateSuccess(response)
        // Verify the actual saved value, including operator policy and validation effects.
        return try await setting(key: key)
    }

    private func refreshCSRF() async throws {
        let token = try decode(CSRFResponse.self, await send(path: "/auth/csrf-token"))
        guard !token.csrfToken.isEmpty else { throw APIError.invalidResponse }
        csrfToken = token.csrfToken
        authContext = token.authContext
    }

    private func send(path: String, method: String = "GET", query: [URLQueryItem] = [],
                      body: Data? = nil, contentType: String = "application/json",
                      mutation: Bool = false) async throws -> HTTPResponse {
        if mutation && csrfToken == nil { try await refreshCSRF() }
        var parts = URLComponents(url: try endpoint.url(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { parts.queryItems = query }
        var request = URLRequest(url: parts.url!)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        if let expectedInstance { request.setValue(expectedInstance, forHTTPHeaderField: "X-Deepdesk-Request") }
        if body != nil { request.setValue(contentType, forHTTPHeaderField: "Content-Type") }
        if mutation {
            request.setValue(csrfToken, forHTTPHeaderField: "X-CSRF-Token")
            if let authContext { request.setValue(authContext, forHTTPHeaderField: "X-LDR-Auth-Context") }
        }
        let response = try await transport.send(request)
        if let expectedInstance, response.header("X-Deepdesk-Instance") != expectedInstance {
            throw APIError.instanceMismatch
        }
        return response
    }

    private func decode<T: Decodable>(_ type: T.Type, _ response: HTTPResponse) throws -> T {
        try validateSuccess(response)
        do { return try decoder.decode(type, from: response.data) }
        catch { throw APIError.invalidResponse }
    }

    private func validateSuccess(_ response: HTTPResponse) throws {
        guard (200...299).contains(response.status) else { throw error(for: response) }
    }

    private func error(for response: HTTPResponse) -> APIError {
        switch response.status {
        case 301...399, 401: return .unauthorized
        case 409: return .unauthorized
        case 403 where response.header("X-LDR-CSRF-Rejected") == "1": return .csrfExpired
        case 403: return .server(status: 403, message: "This action was blocked by the engine’s security or operator policy. Reconnect if your session expired.")
        case 429: return .server(status: 429, message: "The engine is busy or rate-limiting requests. Wait before trying again.")
        default:
            // JSON error strings only. Never surface HTML, headers, or full response snapshots.
            let value = try? decoder.decode(JSONValue.self, from: response.data)
            let message = value?["error"]?.string ?? value?["message"]?.string ?? "The request could not be completed."
            return .server(status: response.status, message: String(message.prefix(500)))
        }
    }

    private func validateID(_ id: String) throws {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
        guard !id.isEmpty, id.count <= 128, id.unicodeScalars.allSatisfy(allowed.contains) else { throw APIError.invalidPath }
    }
}
