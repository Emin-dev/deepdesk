import Foundation

public struct LocalIdentity: Codable, Equatable, Sendable {
    public let username: String
    public let password: String
    public init(username: String, password: String) { self.username = username; self.password = password }
}

public enum IdentityMarker: String, Codable, Sendable { case prepared, registrationAttempted, registered }

public protocol IdentityVault: Sendable {
    func read() async throws -> LocalIdentity?
    func store(_ identity: LocalIdentity) async throws
}

public protocol IdentityMarkerStore: Sendable {
    func read() async throws -> IdentityMarker?
    func write(_ marker: IdentityMarker) async throws
}

/// Success means the authenticated session has been checked against this exact identity.
public protocol LocalAccountClient: Sendable {
    func registerLocalIdentity(_ identity: LocalIdentity) async throws
    func loginLocalIdentity(_ identity: LocalIdentity) async throws
}

public enum IdentityError: Error, LocalizedError, Equatable, Sendable {
    case consentRequired, recoveryRequired, keychainUnavailable, persistenceFailed, untrustedBuild, reconciliationRequired, operationInProgress
    public var errorDescription: String? {
        switch self {
        case .operationInProgress: "Local setup is already in progress."
        case .consentRequired: "Review how Deepdesk protects your local research before continuing."
        case .recoveryRequired: "An existing research identity or encrypted database was found, but its key is unavailable. Unlock or restore the original Keychain. Deepdesk will not create a replacement key."
        case .keychainUnavailable: "The macOS Keychain is locked or access was denied. Unlock it or allow this signed Deepdesk app to access its key, then retry."
        case .persistenceFailed: "Deepdesk could not safely save and verify its local encryption key. No account was created."
        case .untrustedBuild: "This build has no verified production signing identity. Encrypted onboarding is disabled until you install a signed Deepdesk build."
        case .reconciliationRequired: "Local account setup could not be confirmed. Deepdesk kept the original key and will only retry sign-in. It will not create a replacement account."
        }
    }
}

/// Persistent transitions make a dropped registration response safe: it never triggers a second registration.
public actor LocalIdentityCoordinator {
    private let vault: any IdentityVault
    private let markers: any IdentityMarkerStore
    private let generate: @Sendable () throws -> LocalIdentity
    private var operationInProgress = false

    public init(vault: any IdentityVault, markers: any IdentityMarkerStore,
                generate: @escaping @Sendable () throws -> LocalIdentity) {
        self.vault = vault
        self.markers = markers
        self.generate = generate
    }

    public func prepare(consentGranted: Bool, existingEncryptedData: Bool, signingIdentityVerified: Bool) async throws {
        guard !operationInProgress else { throw IdentityError.operationInProgress }
        operationInProgress = true
        defer { operationInProgress = false }
        guard signingIdentityVerified else { throw IdentityError.untrustedBuild }
        let existing = try await vault.read()
        let marker = try await markers.read()
        if existing != nil { return }
        guard marker == nil, !existingEncryptedData else { throw IdentityError.recoveryRequired }
        guard consentGranted else { throw IdentityError.consentRequired }
        let identity = try generate()
        try await vault.store(identity)
        guard try await vault.read() == identity else { throw IdentityError.persistenceFailed }
        // The credential must be durable and read back before any registration is permitted.
        try await markers.write(.prepared)
        guard try await markers.read() == .prepared else { throw IdentityError.persistenceFailed }
    }

    /// Returns only the confirmed username, never the encryption credential.
    @discardableResult
    public func authenticate(using client: any LocalAccountClient) async throws -> String {
        guard !operationInProgress else { throw IdentityError.operationInProgress }
        operationInProgress = true
        defer { operationInProgress = false }
        guard let identity = try await vault.read() else { throw IdentityError.recoveryRequired }
        if try await markers.read() == .prepared {
            try await markers.write(.registrationAttempted)
            guard try await markers.read() == .registrationAttempted else { throw IdentityError.persistenceFailed }
            do {
                try await client.registerLocalIdentity(identity)
                try await markers.write(.registered)
                return identity.username
            } catch {
                // An account may exist even if the server lost the response. Reconcile only by sign-in.
                do { try await client.loginLocalIdentity(identity) }
                catch { throw IdentityError.reconciliationRequired }
                try await markers.write(.registered)
                return identity.username
            }
        }
        // Missing marker with existing Keychain material is also login-only; never infer a fresh account.
        try await client.loginLocalIdentity(identity)
        try await markers.write(.registered)
        return identity.username
    }
}

extension ResearchAPI: LocalAccountClient {
    public func registerLocalIdentity(_ identity: LocalIdentity) async throws {
        let state = try await register(username: identity.username, password: identity.password,
                                       confirmation: identity.password, acknowledgedNoRecovery: true)
        try await verifyLocalIdentity(state, expectedUsername: identity.username)
    }
    public func loginLocalIdentity(_ identity: LocalIdentity) async throws {
        let state = try await signIn(username: identity.username, password: identity.password)
        try await verifyLocalIdentity(state, expectedUsername: identity.username)
    }

    private func verifyLocalIdentity(_ state: AuthState, expectedUsername: String) async throws {
        guard state.authenticated, state.username == expectedUsername else {
            // Never adopt another account's session or record bootstrap success.
            // Clear its cookies and auth context without logging either identity or any secret.
            await disconnect()
            throw IdentityError.reconciliationRequired
        }
    }
}
