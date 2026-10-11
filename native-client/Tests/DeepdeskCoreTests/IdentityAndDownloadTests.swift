import XCTest
@testable import DeepdeskCore
import Foundation

private actor TestVault: IdentityVault {
    var identity: LocalIdentity?
    var denyWrites = false
    var writes = 0
    init(identity: LocalIdentity? = nil, denyWrites: Bool = false) { self.identity = identity; self.denyWrites = denyWrites }
    func read() async throws -> LocalIdentity? { identity }
    func store(_ identity: LocalIdentity) async throws {
        if denyWrites { throw IdentityError.keychainUnavailable }
        writes += 1
        self.identity = identity
    }
    func writeCount() -> Int { writes }
}
private actor TestMarkers: IdentityMarkerStore {
    var marker: IdentityMarker?
    init(_ marker: IdentityMarker? = nil) { self.marker = marker }
    func read() async throws -> IdentityMarker? { marker }
    func write(_ marker: IdentityMarker) async throws { self.marker = marker }
}
private actor TestAccounts: LocalAccountClient {
    var registrationFails: Bool
    var loginFails: Bool
    var registrations = 0
    var logins = 0
    init(registrationFails: Bool = false, loginFails: Bool = false) { self.registrationFails = registrationFails; self.loginFails = loginFails }
    func registerLocalIdentity(_ identity: LocalIdentity) async throws {
        registrations += 1
        try await Task.sleep(for: .milliseconds(20))
        if registrationFails { throw APIError.connectionUnavailable }
    }
    func loginLocalIdentity(_ identity: LocalIdentity) async throws {
        logins += 1
        if loginFails { throw APIError.rejectedCredentials }
    }
    func counts() -> (Int, Int) { (registrations, logins) }
}

@MainActor
final class IdentityAndDownloadTests: XCTestCase {
    private let identity = LocalIdentity(username: "synthetic_test", password: "synthetic-only-a1")

    func testCredentialIsPersistedBeforeRegistration() async throws {
        let vault = TestVault()
        let markers = TestMarkers()
        let value = identity
        let coordinator = LocalIdentityCoordinator(vault: vault, markers: markers, generate: { value })
        try await coordinator.prepare(consentGranted: true, existingEncryptedData: false, signingIdentityVerified: true)
        let stored = try await vault.read()
        let marker = try await markers.read()
        XCTAssertEqual(stored, identity)
        XCTAssertEqual(marker, .prepared)
        let accounts = TestAccounts()
        try await coordinator.authenticate(using: accounts)
        let result = await accounts.counts()
        XCTAssertEqual(result.0, 1)
        XCTAssertEqual(result.1, 0)
        let final = try await markers.read()
        XCTAssertEqual(final, .registered)
    }

    func testAmbiguousRegistrationReconcilesByLoginOnly() async throws {
        let vault = TestVault(identity: identity)
        let markers = TestMarkers(.prepared)
        let coordinator = LocalIdentityCoordinator(vault: vault, markers: markers, generate: { throw IdentityError.persistenceFailed })
        let accounts = TestAccounts(registrationFails: true)
        try await coordinator.authenticate(using: accounts)
        try await coordinator.authenticate(using: accounts)
        let counts = await accounts.counts()
        XCTAssertEqual(counts.0, 1)
        XCTAssertEqual(counts.1, 2)
    }

    func testUncertainFailedRegistrationNeverCreatesReplacement() async throws {
        let vault = TestVault(identity: identity)
        let markers = TestMarkers(.registrationAttempted)
        let coordinator = LocalIdentityCoordinator(vault: vault, markers: markers, generate: { throw IdentityError.persistenceFailed })
        let accounts = TestAccounts(loginFails: true)
        do { try await coordinator.authenticate(using: accounts); XCTFail("Expected failed login") } catch { }
        let counts = await accounts.counts()
        XCTAssertEqual(counts.0, 0)
        XCTAssertEqual(counts.1, 1)
    }

    func testMissingKeyWithExistingDataFailsClosed() async throws {
        let vault = TestVault()
        let coordinator = LocalIdentityCoordinator(vault: vault, markers: TestMarkers(), generate: { throw IdentityError.persistenceFailed })
        do {
            try await coordinator.prepare(consentGranted: true, existingEncryptedData: true, signingIdentityVerified: true)
            XCTFail("Expected recovery")
        } catch { XCTAssertEqual(error as? IdentityError, .recoveryRequired) }
        let writes = await vault.writeCount()
        XCTAssertEqual(writes, 0)
    }

    func testUnsignedBuildCannotCreateCredential() async throws {
        let vault = TestVault()
        let coordinator = LocalIdentityCoordinator(vault: vault, markers: TestMarkers(), generate: { throw IdentityError.persistenceFailed })
        do {
            try await coordinator.prepare(consentGranted: true, existingEncryptedData: false, signingIdentityVerified: false)
            XCTFail("Expected signing gate")
        } catch { XCTAssertEqual(error as? IdentityError, .untrustedBuild) }
        let writes = await vault.writeCount()
        XCTAssertEqual(writes, 0)
    }

    func testKeychainDenialDoesNotRecordRegistration() async throws {
        let vault = TestVault(denyWrites: true)
        let markers = TestMarkers()
        let value = identity
        let coordinator = LocalIdentityCoordinator(vault: vault, markers: markers, generate: { value })
        do { try await coordinator.prepare(consentGranted: true, existingEncryptedData: false, signingIdentityVerified: true); XCTFail("Expected denial") }
        catch { XCTAssertEqual(error as? IdentityError, .keychainUnavailable) }
        let marker = try await markers.read()
        XCTAssertNil(marker)
    }

    func testRangeResumeRequiresExactETagAndBounds() throws {
        XCTAssertEqual(try DownloadResponsePolicy.validate(status: 206, offset: 10, total: 100, expectedETag: "\"v1\"", responseETag: "\"v1\"", contentRange: "bytes 10-99/100"), .resume)
        XCTAssertEqual(try DownloadResponsePolicy.validate(status: 200, offset: 10, total: 100, expectedETag: "v1", responseETag: "v2", contentRange: nil), .restart)
        for range in ["bytes 0-99/100", "bytes 10-98/100", "bytes 10-99/101", "bytes 10-99/*"] {
            XCTAssertThrowsError(try DownloadResponsePolicy.validate(status: 206, offset: 10, total: 100, expectedETag: "v1", responseETag: "v1", contentRange: range))
        }
        XCTAssertThrowsError(try DownloadResponsePolicy.validate(status: 206, offset: 10, total: 100, expectedETag: "v1", responseETag: "v2", contentRange: "bytes 10-99/100"))
        XCTAssertThrowsError(try DownloadResponsePolicy.validate(status: 206, offset: 10, total: 100, expectedETag: "W/v1", responseETag: "W/v1", contentRange: "bytes 10-99/100"))
        XCTAssertThrowsError(try DownloadResponsePolicy.validate(status: 206, offset: 100, total: 100, expectedETag: "v1", responseETag: "v1", contentRange: "bytes 100-99/100"))
    }

    func testDownloadRedirectsStayOnExactHTTPSHosts() {
        let allowed: Set<String> = ["huggingface.co", "us.aws.cdn.hf.co"]
        XCTAssertTrue(DownloadResponsePolicy.acceptsRedirect(URL(string: "https://us.aws.cdn.hf.co/object")!, allowedHosts: allowed))
        for value in ["http://huggingface.co/object", "https://huggingface.co.evil.com/object", "https://evil.amazonaws.com/object", "https://user:password@huggingface.co/object", "https://huggingface.co:8443/object"] {
            XCTAssertFalse(DownloadResponsePolicy.acceptsRedirect(URL(string: value)!, allowedHosts: allowed))
        }
    }
    func testCachePathsRejectTraversalAndSymlinks() throws {
        let root = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString, isDirectory: true)
        let outside = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: outside, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root); try? FileManager.default.removeItem(at: outside) }
        for path in ["../outside/model.json", "/tmp/model.json", "a//model.json", "a/./model.json", "a/../model.json", "a\\b.json"] {
            XCTAssertThrowsError(try SafeModelPath.resolve(root: root, relativePath: path))
        }
        try FileManager.default.createSymbolicLink(at: root.appendingPathComponent("linked"), withDestinationURL: outside)
        XCTAssertThrowsError(try SafeModelPath.resolve(root: root, relativePath: "linked/model.json"))
        XCTAssertNoThrow(try SafeModelPath.resolve(root: root, relativePath: "real/model.json"))
    }

    func testConcurrentBootstrapCannotRegisterTwice() async throws {
        let vault = TestVault(identity: identity)
        let coordinator = LocalIdentityCoordinator(vault: vault, markers: TestMarkers(.prepared), generate: { throw IdentityError.persistenceFailed })
        let accounts = TestAccounts()
        let first = Task { try await coordinator.authenticate(using: accounts) }
        let second = Task { try await coordinator.authenticate(using: accounts) }
        for task in [first, second] {
            do { try await task.value }
            catch { XCTAssertEqual(error as? IdentityError, .operationInProgress) }
        }
        let counts = await accounts.counts()
        XCTAssertEqual(counts.0, 1)
    }

    func testExistingKeyStillRequiresSignedBuild() async throws {
        let coordinator = LocalIdentityCoordinator(vault: TestVault(identity: identity), markers: TestMarkers(.registered), generate: { throw IdentityError.persistenceFailed })
        do { try await coordinator.prepare(consentGranted: true, existingEncryptedData: true, signingIdentityVerified: false); XCTFail("Expected signing rejection") }
        catch { XCTAssertEqual(error as? IdentityError, .untrustedBuild) }
    }

    func testBoundedMetadataReadRejectsOversizedAndLinkedFiles() throws {
        let root = FileManager.default.temporaryDirectory.resolvingSymlinksInPath().appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let file = root.appendingPathComponent("resume.json")
        try Data(repeating: 0, count: 20_000).write(to: file)
        XCTAssertThrowsError(try SafeLocalFile.read(file, maximumBytes: 16_384))
        let linked = root.appendingPathComponent("linked.json")
        try FileManager.default.createSymbolicLink(at: linked, withDestinationURL: file)
        XCTAssertThrowsError(try SafeLocalFile.read(linked, maximumBytes: 30_000))
        try Data("{}".utf8).write(to: file)
        XCTAssertEqual(try SafeLocalFile.read(file, maximumBytes: 1024), Data("{}".utf8))
    }

    func testCuratedCatalogPinsBothModelsAndRejectsUnsafeArtifacts() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "model-catalog", withExtension: "json"))
        let data = try Data(contentsOf: url)
        let catalog = try JSONDecoder().decode(ModelCatalog.self, from: data).validated()
        XCTAssertEqual(catalog.models.map(\.id), ["qwen38-27b-splash", "qwen38-27b-uncensored"])
        XCTAssertEqual(catalog.models[0].draftDirectory, catalog.models[1].draftDirectory)
        XCTAssertTrue(catalog.models.allSatisfy(\.thinkingSupported))
        for invalid in ["../escape.safetensors", "/absolute.json", "target/model.pkl", "target//config.json"] {
            var root = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            var models = try XCTUnwrap(root["models"] as? [[String: Any]])
            var artifacts = try XCTUnwrap(models[0]["artifacts"] as? [[String: Any]])
            artifacts[0]["path"] = invalid
            models[0]["artifacts"] = artifacts
            root["models"] = models
            let changed = try JSONDecoder().decode(ModelCatalog.self, from: JSONSerialization.data(withJSONObject: root))
            XCTAssertThrowsError(try changed.validated(), invalid)
        }
    }

}
