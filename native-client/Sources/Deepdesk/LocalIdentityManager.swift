#if os(macOS)
import Foundation
import SwiftUI
import Security
import DeepdeskCore

actor KeychainIdentityVault: IdentityVault {
    private let service = "dev.emin.deepdesk.local-identity.v1"
    private let account = "encrypted-research"
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: account,
         kSecUseDataProtectionKeychain as String: true,
         kSecAttrSynchronizable as String: false]
    }

    func read() async throws -> LocalIdentity? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(request as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data, data.count <= 4096 else { throw IdentityError.keychainUnavailable }
        guard let identity = try? JSONDecoder().decode(LocalIdentity.self, from: data) else { throw IdentityError.recoveryRequired }
        return identity
    }

    func store(_ identity: LocalIdentity) async throws {
        var request = query
        request[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        request[kSecValueData as String] = try JSONEncoder().encode(identity)
        request[kSecAttrLabel as String] = "Deepdesk local research encryption key"
        // Never overwrite or rotate a prior key. Duplicate-item is a recovery/reconciliation condition.
        guard SecItemAdd(request as CFDictionary, nil) == errSecSuccess else { throw IdentityError.persistenceFailed }
    }
}

actor FileIdentityMarkerStore: IdentityMarkerStore {
    private let url: URL
    init(url: URL) { self.url = url }
    func read() async throws -> IdentityMarker? {
        try SafeModelPath.rejectLinks(url)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        let values = try url.resourceValues(forKeys: [.isSymbolicLinkKey, .isRegularFileKey])
        guard values.isSymbolicLink != true, values.isRegularFile == true else { throw IdentityError.recoveryRequired }
        guard let value = try? JSONDecoder().decode(IdentityMarker.self, from: SafeLocalFile.read(url, maximumBytes: 1024)) else { throw IdentityError.recoveryRequired }
        return value
    }
    func write(_ marker: IdentityMarker) async throws {
        try SafeModelPath.rejectLinks(url)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        if FileManager.default.fileExists(atPath: url.path) {
            let values = try url.resourceValues(forKeys: [.isSymbolicLinkKey])
            guard values.isSymbolicLink != true else { throw IdentityError.recoveryRequired }
        }
        try JSONEncoder().encode(marker).write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
}

@MainActor
final class LocalIdentityManager: ObservableObject {
    @Published var disclosureAccepted = false
    @Published private(set) var needsDisclosure = true
    @Published private(set) var errorMessage: String?
    private(set) var coordinator: LocalIdentityCoordinator?
    private var existingEncryptedData = true

    init() {
        do {
            let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                      appropriateFor: nil, create: true)
            let root = support.appendingPathComponent("Deepdesk", isDirectory: true)
            existingEncryptedData = try Self.hasEncryptedEvidence(root: root)
            let markerURL = root.appendingPathComponent("identity-state.json")
            coordinator = LocalIdentityCoordinator(vault: KeychainIdentityVault(),
                                                    markers: FileIdentityMarkerStore(url: markerURL),
                                                    generate: Self.makeIdentity)
        } catch { errorMessage = IdentityError.recoveryRequired.localizedDescription }
    }

    func prepare() async -> Bool {
        guard let coordinator else { return false }
        do {
            try await coordinator.prepare(consentGranted: disclosureAccepted, existingEncryptedData: existingEncryptedData,
                                          signingIdentityVerified: Self.productionSignatureVerified())
            needsDisclosure = false
            errorMessage = nil
            return true
        } catch {
            if error as? IdentityError == .consentRequired { needsDisclosure = true }
            else { errorMessage = error.localizedDescription }
            return false
        }
    }

    nonisolated private static func makeIdentity() throws -> LocalIdentity {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw IdentityError.persistenceFailed }
        return LocalIdentity(username: "deepdesk_" + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
                             password: "d1-" + Data(bytes).base64EncodedString())
    }

    nonisolated private static func hasEncryptedEvidence(root: URL) throws -> Bool {
        let manager = FileManager.default
        try SafeModelPath.rejectLinks(root)
        try SafeModelPath.rejectLinks(root.appendingPathComponent("Engine"))
        if manager.fileExists(atPath: root.path) {
            guard try root.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true else { throw IdentityError.recoveryRequired }
        }
        let encrypted = root.appendingPathComponent("Engine/encrypted_databases", isDirectory: true)
        try SafeModelPath.rejectLinks(encrypted)
        guard manager.fileExists(atPath: encrypted.path) else { return false }
        guard try encrypted.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink != true else { throw IdentityError.recoveryRequired }
        // Any existing encrypted DB or backup blocks a new key. Unreadable directories throw and fail closed.
        let entries = try manager.contentsOfDirectory(at: encrypted, includingPropertiesForKeys: [.isSymbolicLinkKey], options: [])
        return !entries.isEmpty
    }

    nonisolated private static func productionSignatureVerified() -> Bool {
        guard let expectedTeam = Bundle.main.object(forInfoDictionaryKey: "DeepdeskSigningTeamID") as? String,
              !expectedTeam.isEmpty else { return false }
        var code: SecCode?
        guard SecCodeCopySelf([], &code) == errSecSuccess, let code,
              SecCodeCheckValidity(code, [], nil) == errSecSuccess else { return false }
        var staticCode: SecStaticCode?
        guard SecCodeCopyStaticCode(code, [], &staticCode) == errSecSuccess, let staticCode else { return false }
        var information: CFDictionary?
        guard SecCodeCopySigningInformation(staticCode, SecCSFlags(rawValue: kSecCSSigningInformation), &information) == errSecSuccess,
              let info = information as? [String: Any],
              let team = info[kSecCodeInfoTeamIdentifier as String] as? String, team == expectedTeam,
              let flags = info[kSecCodeInfoFlags as String] as? UInt32,
              flags & UInt32(kSecCodeSignatureAdhoc) == 0 else { return false }
        return true
    }
}
#endif
