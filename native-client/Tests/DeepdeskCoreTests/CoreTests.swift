import XCTest
@testable import DeepdeskCore
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

private actor MockTransport: HTTPTransport {
    enum Result: Sendable { case response(HTTPResponse), failure(APIError) }
    private var results: [Result]
    private var requests: [URLRequest] = []
    private(set) var invalidated = false
    init(_ results: [Result]) { self.results = results }
    func send(_ request: URLRequest) async throws -> HTTPResponse {
        requests.append(request)
        guard !results.isEmpty else { throw APIError.invalidResponse }
        switch results.removeFirst() {
        case .response(let response): return response
        case .failure(let error): throw error
        }
    }
    func invalidate() async { invalidated = true }
    func recorded() -> [URLRequest] { requests }
}

private func json(_ body: String, status: Int = 200, headers: [String: String] = [:]) -> MockTransport.Result {
    .response(HTTPResponse(data: Data(body.utf8), status: status, headers: headers))
}

@MainActor
final class CoreTests: XCTestCase {
    func testEndpointCannotBecomeRemote() throws {
        let endpoint = try LocalEndpoint(port: 5000)
        XCTAssertEqual(try endpoint.url(path: "/auth/check").absoluteString, "http://127.0.0.1:5000/auth/check")
        for path in ["//evil.example/login", "https://evil.example/login", "/\\evil", "/test?evil=yes", "/test#fragment"] {
            XCTAssertThrowsError(try endpoint.url(path: path))
        }
        XCTAssertThrowsError(try LocalEndpoint(port: 0))
        XCTAssertThrowsError(try LocalEndpoint(port: 65536))
    }

    func testSourceURLsRejectExecutableAndCredentialSchemes() {
        for value in ["javascript:alert(1)", "file:///etc/passwd", "httpjavascript://evil", "https://user:secret@example.com", "https://example.com/path with space", "https://"] {
            XCTAssertNil(SafeSourceURL.parse(value), value)
        }
        XCTAssertEqual(SafeSourceURL.parse("https://example.org/paper?q=a%20b#page")?.host, "example.org")
        XCTAssertNotNil(SafeSourceURL.parse("http://example.org/"))
    }

    func testFormEncodingDoesNotChangePasswords() throws {
        let password = "+ & = % café 密码"
        let encoded = String(decoding: FormEncoding.encode(["password": password, "username": "a+b"]), as: UTF8.self)
        XCTAssertTrue(encoded.contains("%2B"))
        XCTAssertTrue(encoded.contains("%26"))
        XCTAssertTrue(encoded.contains("%3D"))
        XCTAssertTrue(encoded.contains("%25"))
        let parts = URLComponents(string: "http://127.0.0.1/?\(encoded)")!
        XCTAssertEqual(parts.queryItems?.first(where: { $0.name == "password" })?.value, password)
    }

    func testLoginRotatesCSRFAndIncludesAccountContext() async throws {
        let transport = MockTransport([
            json(#"{"csrf_token":"pre","auth_context":null}"#),
            json("", status: 302),
            json(#"{"authenticated":true,"username":"alex"}"#),
            json(#"{"csrf_token":"post","auth_context":"account-1"}"#),
            json(#"{"status":"success","research_id":"d918775a-9706-4f5d-8d50-0958cf9f45c2"}"#)
        ])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        let auth = try await api.signIn(username: "alex", password: "a1+&=%")
        XCTAssertTrue(auth.authenticated)
        let accepted = try await api.start(ResearchStartRequest(query: "Unicode question: 脱炭素?"))
        XCTAssertEqual(accepted.status, "success")
        let requests = await transport.recorded()
        XCTAssertEqual(requests.map { $0.url!.path }, ["/auth/csrf-token", "/auth/login", "/auth/check", "/auth/csrf-token", "/api/start_research"])
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "X-CSRF-Token"), "pre")
        XCTAssertEqual(requests[1].value(forHTTPHeaderField: "Content-Type"), "application/x-www-form-urlencoded")
        XCTAssertEqual(requests[4].value(forHTTPHeaderField: "X-CSRF-Token"), "post")
        XCTAssertEqual(requests[4].value(forHTTPHeaderField: "X-LDR-Auth-Context"), "account-1")
        XCTAssertTrue(String(decoding: requests[1].httpBody!, as: UTF8.self).contains("remember=false"))
    }

    func testWrongPasswordDoesNotDecodeHTML() async throws {
        let transport = MockTransport([json(#"{"csrf_token":"pre"}"#), json("<html>bad password</html>", status: 401)])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        do {
            _ = try await api.signIn(username: "alex", password: "wrong")
            XCTFail("Expected rejected credentials")
        } catch { XCTAssertEqual(error as? APIError, .rejectedCredentials) }
        let requests = await transport.recorded()
        XCTAssertEqual(requests.count, 2)
    }

    func testAmbiguousStartIsNeverRetried() async throws {
        let transport = MockTransport([json(#"{"csrf_token":"token","auth_context":"account"}"#), .failure(.connectionUnavailable)])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        do { _ = try await api.start(ResearchStartRequest(query: "test")); XCTFail("Expected disconnect") }
        catch { XCTAssertEqual(error as? APIError, .connectionUnavailable) }
        let requests = await transport.recorded()
        XCTAssertEqual(requests.filter { $0.httpMethod == "POST" }.count, 1)
    }

    func testQueuedStartAndExactPayloadNames() async throws {
        let transport = MockTransport([
            json(#"{"csrf_token":"token","auth_context":"account"}"#),
            json(#"{"status":"queued","research_id":"run-123","queue_position":2}"#)
        ])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        var request = ResearchStartRequest(query: "Question", mode: .detailed)
        request.searchEngine = "searxng"
        request.llmRequireLocalEndpoint = true
        request.embeddingsRequireLocal = true
        let value = try await api.start(request)
        XCTAssertEqual(value.queuePosition, 2)
        let calls = await transport.recorded()
        let body = try JSONDecoder().decode(JSONValue.self, from: calls.last!.httpBody!)
        XCTAssertEqual(body["search_engine"]?.string, "searxng")
        XCTAssertNil(body["search_engines"])
        XCTAssertEqual(body["mode"]?.string, "detailed")
        XCTAssertEqual(body["llm_require_local_endpoint"], .bool(true))
    }

    func testStatusShapesAndUnknownStatusStayHonest() throws {
        for status in ["completed", "failed", "suspended", "error", "cancelled"] { XCTAssertTrue(JobPhase(status).isTerminal) }
        for status in ["queued", "pending", "in_progress"] { XCTAssertTrue(JobPhase(status).isActive) }
        XCTAssertFalse(JobPhase("future_state").isTerminal)
        let status = try JSONDecoder().decode(ResearchProgress.self, from: Data(#"{"status":"in_progress","progress":null,"metadata":{}}"#.utf8))
        XCTAssertNil(status.fraction)
        XCTAssertNil(status.logEntry)
        let complete = try JSONDecoder().decode(ResearchProgress.self, from: Data(#"{"status":"completed","progress":105}"#.utf8))
        XCTAssertEqual(complete.fraction, 1)
    }

    func testHistoryUsesWrappedEndpointAndNullableFields() async throws {
        let transport = MockTransport([json(#"{"status":"success","items":[{"id":"abc","title":null,"query":"Question","status":"completed","created_at":null,"completed_at":null,"duration_seconds":null}]}"#)])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        let items = try await api.history(offset: 50)
        XCTAssertEqual(items.first?.displayTitle, "Question")
        let calls = await transport.recorded()
        XCTAssertEqual(calls[0].url!.path, "/history/api")
        XCTAssertTrue(calls[0].url!.absoluteString.contains("offset=50"))
    }

    func testReportSummaryAliasAndSourcesNoInventedCitationNumber() throws {
        let report = try JSONDecoder().decode(ResearchReport.self, from: Data(#"{"summary":"Report [7]","sources":[{"url":"https://example.org","title":"Evidence"}],"findings":[],"metadata":{"title":null}}"#.utf8))
        XCTAssertEqual(report.content, "Report [7]")
        XCTAssertEqual(report.sources[0].id, "https://example.org")
        XCTAssertNil(report.title)
        let empty = try JSONDecoder().decode(ResearchReport.self, from: Data(#"{"content":"No sources"}"#.utf8))
        XCTAssertTrue(empty.sources.isEmpty)
    }

    func testStopAcknowledgementIsNotTerminalProof() async throws {
        let transport = MockTransport([
            json(#"{"csrf_token":"token","auth_context":"account"}"#),
            json(#"{"status":"success","message":"Research termination requested"}"#),
            json(#"{"status":"in_progress","progress":20}"#),
            json(#"{"status":"suspended","progress":20}"#)
        ])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        try await api.stop(id: "run-123")
        let first = try await api.progress(id: "run-123")
        let second = try await api.progress(id: "run-123")
        XCTAssertFalse(first.phase.isTerminal)
        XCTAssertEqual(second.phase, .stopped)
    }

    func testLockedSettingIsNotRetriedOrWrittenAround() async throws {
        let transport = MockTransport([json(#"{"csrf_token":"token","auth_context":"account"}"#), json(#"{"error":"Locked"}"#, status: 403)])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        do { _ = try await api.updateSetting(key: "llm.model", value: "local-model"); XCTFail("Expected lock") }
        catch {
            guard let apiError = error as? APIError else { return XCTFail("Wrong error") }
            if case .server(let status, _) = apiError { XCTAssertEqual(status, 403) }
            else { XCTFail("Wrong error") }
        }
        let calls = await transport.recorded()
        XCTAssertEqual(calls.count, 2)
        do { _ = try await api.updateSetting(key: "llm.openai.api_key", value: "forbidden"); XCTFail("Expected key rejection") }
        catch { XCTAssertNotNil(error as? APIError) }
        let after = await transport.recorded()
        XCTAssertEqual(after.count, 2)
    }

    func testVerifiedCSRFRejectionDoesNotReplayMutation() async throws {
        let transport = MockTransport([
            json(#"{"csrf_token":"token","auth_context":"account"}"#),
            json(#"{"error":"Expired"}"#, status: 403, headers: ["X-LDR-CSRF-Rejected": "1"])
        ])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        do { try await api.stop(id: "run"); XCTFail("Expected token expiry") }
        catch { XCTAssertEqual(error as? APIError, .csrfExpired) }
        let calls = await transport.recorded()
        XCTAssertEqual(calls.count, 2)
    }

    func testManagedInstanceIdentitySentAndVerified() async throws {
        let transport = MockTransport([
            json(#"{"authenticated":false}"#, status: 401, headers: ["X-Deepdesk-Instance": "expected"]),
            json(#"{"authenticated":false}"#, status: 401, headers: ["X-Deepdesk-Instance": "imposter"])
        ])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport, expectedInstance: "expected")
        let first = try await api.checkAuthentication()
        XCTAssertFalse(first.authenticated)
        do { _ = try await api.checkAuthentication(); XCTFail("Expected identity rejection") }
        catch { XCTAssertEqual(error as? APIError, .instanceMismatch) }
        let calls = await transport.recorded()
        XCTAssertEqual(calls[0].value(forHTTPHeaderField: "X-Deepdesk-Request"), "expected")
    }

    func testBadIDsNeverReachTransport() async throws {
        let transport = MockTransport([])
        let api = ResearchAPI(endpoint: try LocalEndpoint(), transport: transport)
        for id in ["../other", "a/b", "?query", "", "évil"] {
            do { _ = try await api.progress(id: id); XCTFail("Expected rejected ID") }
            catch { XCTAssertEqual(error as? APIError, .invalidPath) }
        }
        let calls = await transport.recorded()
        XCTAssertTrue(calls.isEmpty)
    }
}
