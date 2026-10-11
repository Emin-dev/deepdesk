import Foundation

public struct AuthState: Decodable, Sendable {
    public let authenticated: Bool
    public let username: String?
}

struct CSRFResponse: Decodable, Sendable {
    let csrfToken: String
    let authContext: String?
    enum CodingKeys: String, CodingKey {
        case csrfToken = "csrf_token", authContext = "auth_context"
    }
}

public enum ResearchMode: String, Codable, CaseIterable, Identifiable, Sendable {
    case quick, detailed
    public var id: String { rawValue }
    public var label: String { self == .quick ? "Quick" : "Detailed" }
}

public struct ResearchStartRequest: Encodable, Sendable {
    public let query: String
    public let mode: ResearchMode
    public var modelProvider: String?
    public var model: String?
    public var searchEngine: String?
    public var customEndpoint: String?
    public var strategy: String?
    public var policyEgressScope: String?
    public var llmRequireLocalEndpoint: Bool?
    public var embeddingsRequireLocal: Bool?

    public init(query: String, mode: ResearchMode = .quick) {
        self.query = query
        self.mode = mode
    }

    enum CodingKeys: String, CodingKey {
        case query, mode, model, strategy
        case modelProvider = "model_provider", searchEngine = "search_engine", customEndpoint = "custom_endpoint"
        case policyEgressScope = "policy_egress_scope"
        case llmRequireLocalEndpoint = "llm_require_local_endpoint"
        case embeddingsRequireLocal = "embeddings_require_local"
    }
}

public struct ResearchAccepted: Decodable, Sendable {
    public let status: String
    public let researchID: String
    public let queuePosition: Int?
    public let message: String?
    enum CodingKeys: String, CodingKey {
        case status, message
        case researchID = "research_id", queuePosition = "queue_position"
    }
}

public enum JobPhase: Equatable, Sendable {
    case queued, running, completed, failed, stopped, unknown(String)
    public init(_ raw: String) {
        switch raw {
        case "queued", "pending": self = .queued
        case "in_progress": self = .running
        case "completed": self = .completed
        case "failed", "error": self = .failed
        case "suspended", "cancelled": self = .stopped
        default: self = .unknown(raw)
        }
    }
    public var isTerminal: Bool {
        switch self { case .completed, .failed, .stopped: true; default: false }
    }
    public var isActive: Bool { self == .queued || self == .running }
    public var label: String {
        switch self {
        case .queued: "Queued"
        case .running: "Researching"
        case .completed: "Completed"
        case .failed: "Failed"
        case .stopped: "Stopped"
        case .unknown(let raw): "Status: \(raw)"
        }
    }
}

public struct ResearchProgress: Decodable, Sendable {
    public let status: String
    public let progress: Double?
    public let completedAt: String?
    public let metadata: [String: JSONValue]?
    public let logEntry: ProgressLog?
    public var phase: JobPhase { JobPhase(status) }
    public var fraction: Double? { progress.map { min(1, max(0, $0 / 100)) } }
    public var failureMessage: String? {
        metadata?["error_info"]?["message"]?.string
    }
    public var failureSuggestion: String? {
        metadata?["error_info"]?["suggestion"]?.string
    }
    enum CodingKeys: String, CodingKey {
        case status, progress, metadata
        case completedAt = "completed_at", logEntry = "log_entry"
    }
}

public struct ProgressLog: Decodable, Sendable {
    public let message: String?
    public let time: String?
    public let type: String?
}

public struct ResearchHistoryItem: Decodable, Identifiable, Sendable {
    public let id: String
    public let title: String?
    public let query: String
    public let mode: String?
    public let status: String
    public let createdAt: String?
    public let completedAt: String?
    public let durationSeconds: Double?
    public var displayTitle: String { title.flatMap { $0.isEmpty ? nil : $0 } ?? query }
    public var phase: JobPhase { JobPhase(status) }
    enum CodingKeys: String, CodingKey {
        case id, title, query, mode, status
        case createdAt = "created_at", completedAt = "completed_at", durationSeconds = "duration_seconds"
    }
}

struct HistoryResponse: Decodable, Sendable {
    let status: String
    let items: [ResearchHistoryItem]
}

public struct ResearchSource: Decodable, Identifiable, Sendable {
    public let url: String
    public let title: String?
    public var id: String { url }
    public var safeURL: URL? { SafeSourceURL.parse(url) }
    public var displayTitle: String { title.flatMap { $0.isEmpty ? nil : $0 } ?? safeURL?.host ?? "Source" }
}

public enum SafeSourceURL {
    /// Source clicks are the only UI action that can open a non-loopback URL.
    public static func parse(_ value: String) -> URL? {
        guard !value.contains(where: { $0.isWhitespace || $0.isNewline }),
              let parts = URLComponents(string: value),
              ["https", "http"].contains(parts.scheme?.lowercased() ?? ""),
              let host = parts.host, !host.isEmpty,
              parts.user == nil, parts.password == nil,
              let url = parts.url else { return nil }
        return url
    }
}

public struct ResearchReport: Decodable, Sendable {
    public let content: String
    public let sources: [ResearchSource]
    public let metadata: [String: JSONValue]?
    public var title: String? { metadata?["title"]?.string }
    enum CodingKeys: String, CodingKey { case content, summary, sources, metadata }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        content = try c.decodeIfPresent(String.self, forKey: .content)
            ?? c.decodeIfPresent(String.self, forKey: .summary) ?? ""
        sources = try c.decodeIfPresent([ResearchSource].self, forKey: .sources) ?? []
        metadata = try c.decodeIfPresent([String: JSONValue].self, forKey: .metadata)
    }
}

public struct SettingMetadata: Decodable, Sendable {
    public let key: String?
    public let value: JSONValue?
    public let name: String?
    public let description: String?
    public let editable: Bool?
    public let options: JSONValue?
    public var stringValue: String { value?.string ?? "" }
}

public struct EngineSettings: Sendable {
    public let values: [String: SettingMetadata]
    public init(values: [String: SettingMetadata]) { self.values = values }
    public subscript(_ key: String) -> SettingMetadata? { values[key] }
    public var provider: String { values["llm.provider"]?.stringValue ?? "" }
    public var model: String { values["llm.model"]?.stringValue ?? "" }
    public var searchEngine: String { values["search.tool"]?.stringValue ?? "" }
    public var egressScope: String { values["policy.egress_scope"]?.stringValue ?? "" }
}

public enum SettingsKey {
    // Deliberately allowlist non-secret settings. Never load or round-trip API-key fields.
    public static let readable = ["llm.provider", "llm.model", "search.tool", "policy.egress_scope", "llm.require_local_endpoint", "embeddings.require_local"]
    public static let writable = ["llm.provider", "llm.model", "search.tool"]
}

public struct ModelChoice: Decodable, Hashable, Identifiable, Sendable {
    public let value: String
    public let label: String?
    public let provider: String?
    public var id: String { "\(provider ?? ""):\(value)" }
    public var displayName: String { label ?? value }
}

public struct AvailableModels: Decodable, Sendable {
    public let providers: [String: [ModelChoice]]
    public func choices(for provider: String) -> [ModelChoice] {
        let values = providers["\(provider)_models"] ?? []
        return values.sorted { $0.displayName.localizedStandardCompare($1.displayName) == .orderedAscending }
    }
}
