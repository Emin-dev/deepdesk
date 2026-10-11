import XCTest
@testable import DeepdeskCore
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

private actor IdentityResponseTransport: HTTPTransport {
    private var responses: [HTTPResponse]
    private(set) var invalidated = false
    private(set) var paths: [String] = []
    init(_ responses: [HTTPResponse]) { self.responses = responses }
    func send(_ request: URLRequest) async throws -> HTTPResponse {
        guard !invalidated else { throw APIError.connectionUnavailable }
        paths.append(request.url?.path ?? "") // Do not retain credentials or request bodies.
        guard !responses.isEmpty else { throw APIError.invalidResponse }
        return responses.removeFirst()
    }
    func invalidate() async { invalidated = true }
}

private actor BindingVault: IdentityVault {
    let identity: LocalIdentity
    init(_ identity: LocalIdentity) { self.identity = identity }
    func read() async throws -> LocalIdentity? { identity }
    func store(_ identity: LocalIdentity) async throws { throw IdentityError.persistenceFailed }
}
private actor BindingMarkers: IdentityMarkerStore {
    var marker: IdentityMarker?
    init(_ marker: IdentityMarker? = .prepared) { self.marker = marker }
    func read() async throws -> IdentityMarker? { marker }
    func write(_ marker: IdentityMarker) async throws { self.marker = marker }
}

@MainActor
final class IdentitySessionBindingTests: XCTestCase {
    private let identity = LocalIdentity(username: "synthetic_expected", password: "synthetic-fixture-only-a1")

    private func client(authenticated: Bool, username: String?) throws -> (ResearchAPI, IdentityResponseTransport) {
        var state: [String: Any] = ["authenticated": authenticated]
        if let username { state["username"] = username }
        let responses = [
            HTTPResponse(data: Data(#"{"csrf_token":"synthetic-pre"}"#.utf8), status: 200),
            HTTPResponse(data: Data(), status: 302),
            HTTPResponse(data: try JSONSerialization.data(withJSONObject: state), status: 200),
            HTTPResponse(data: Data(#"{"csrf_token":"synthetic-post","auth_context":"synthetic-context"}"#.utf8), status: 200)
        ]
        let transport = IdentityResponseTransport(responses)
        return (ResearchAPI(endpoint: try LocalEndpoint(), transport: transport), transport)
    }

    private func rejects(registration: Bool, authenticated: Bool, username: String?) async throws {
        let (api, transport) = try client(authenticated: authenticated, username: username)
        do {
            if registration { try await api.registerLocalIdentity(identity) }
            else { try await api.loginLocalIdentity(identity) }
            XCTFail("An unconfirmed local identity must not succeed")
        } catch {
            if authenticated { XCTAssertEqual(error as? IdentityError, .reconciliationRequired) }
            else if registration {
                guard let apiError = error as? APIError, case .invalidInput = apiError else {
                    XCTFail("Expected the existing unauthenticated-registration guard")
                    return
                }
            } else { XCTAssertEqual(error as? APIError, .rejectedCredentials) }
            // authenticated=false is rejected by register/signIn before the identity adapter.
        }
        let invalidated = await transport.invalidated
        let paths = await transport.paths
        if authenticated {
            XCTAssertTrue(invalidated, "A mismatched session must be discarded")
            XCTAssertEqual(paths.count, 4)
        } else {
            XCTAssertEqual(paths.count, 3, "Unauthenticated state must not reach CSRF rotation or research")
        }
        XCTAssertEqual(paths.filter { $0 == "/auth/register" }.count, registration ? 1 : 0)
        XCTAssertEqual(paths.filter { $0 == "/auth/login" }.count, registration ? 0 : 1)
        XCTAssertFalse(paths.contains("/api/start_research"))
    }

    func testLoginRejectsAnotherUsername() async throws {
        try await rejects(registration: false, authenticated: true, username: "synthetic_other")
    }
    func testLoginRejectsMissingUsername() async throws {
        try await rejects(registration: false, authenticated: true, username: nil)
    }
    func testLoginRejectsUnauthenticatedState() async throws {
        try await rejects(registration: false, authenticated: false, username: identity.username)
    }
    func testRegistrationRejectsAnotherUsername() async throws {
        try await rejects(registration: true, authenticated: true, username: "synthetic_other")
    }
    func testRegistrationRejectsMissingUsername() async throws {
        try await rejects(registration: true, authenticated: true, username: nil)
    }
    func testRegistrationRejectsUnauthenticatedState() async throws {
        try await rejects(registration: true, authenticated: false, username: identity.username)
    }
    func testLoginAcceptsExactIdentityAndKeepsSession() async throws {
        let (api, transport) = try client(authenticated: true, username: identity.username)
        try await api.loginLocalIdentity(identity)
        let invalidated = await transport.invalidated
        XCTAssertFalse(invalidated)
    }
    func testRegistrationAcceptsExactIdentityAndKeepsSession() async throws {
        let (api, transport) = try client(authenticated: true, username: identity.username)
        try await api.registerLocalIdentity(identity)
        let invalidated = await transport.invalidated
        XCTAssertFalse(invalidated)
    }
    func testCoordinatorCarriesValidatedUsernameWithoutAnotherAuthCheck() async throws {
        for marker in [IdentityMarker.prepared, IdentityMarker.registered] {
            let (api, transport) = try client(authenticated: true, username: identity.username)
            let markers = BindingMarkers(marker)
            let coordinator = LocalIdentityCoordinator(vault: BindingVault(identity), markers: markers,
                                                       generate: { throw IdentityError.persistenceFailed })
            let verifiedUsername = try await coordinator.authenticate(using: api)
            XCTAssertEqual(verifiedUsername, identity.username)
            let paths = await transport.paths
            XCTAssertEqual(paths.filter { $0 == "/auth/check" }.count, 1)
            let finalMarker = try await markers.read()
            XCTAssertEqual(finalMarker, .registered)
        }
    }
    func testMismatchCannotMarkBootstrapRegisteredOrRepeatRegistration() async throws {
        let (api, transport) = try client(authenticated: true, username: "synthetic_other")
        let markers = BindingMarkers()
        let coordinator = LocalIdentityCoordinator(vault: BindingVault(identity), markers: markers,
                                                   generate: { throw IdentityError.persistenceFailed })
        do { try await coordinator.authenticate(using: api); XCTFail("Expected fail-closed reconciliation") }
        catch { XCTAssertEqual(error as? IdentityError, .reconciliationRequired) }
        let marker = try await markers.read()
        XCTAssertEqual(marker, .registrationAttempted)
        do { try await coordinator.authenticate(using: api); XCTFail("An invalidated session must not become ready") }
        catch { }
        let paths = await transport.paths
        XCTAssertEqual(paths.filter { $0 == "/auth/register" }.count, 1)
        XCTAssertFalse(paths.contains("/auth/login"), "The invalidated transport must refuse further credential requests")
        let finalMarker = try await markers.read()
        XCTAssertEqual(finalMarker, .registrationAttempted)
    }
}
