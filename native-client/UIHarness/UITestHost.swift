import SwiftUI
import DeepdeskCore

// This file belongs only to the separate UI test host target. It is never part of Deepdesk's package executable.
extension Bundle { static var module: Bundle { .main } }

private actor MemoryVault: IdentityVault {
    var value: LocalIdentity?
    func read() async throws -> LocalIdentity? { value }
    func store(_ identity: LocalIdentity) async throws { value = identity }
}
private actor MemoryMarkers: IdentityMarkerStore {
    var value: IdentityMarker?
    func read() async throws -> IdentityMarker? { value }
    func write(_ marker: IdentityMarker) async throws { value = marker }
}

private func decoded<T: Decodable>(_ type: T.Type, _ object: Any) throws -> T {
    try JSONDecoder().decode(type, from: JSONSerialization.data(withJSONObject: object))
}

private actor SyntheticResearchService: ResearchService {
    private var query = ""
    private var phase = "completed"
    private var polls = 0
    private var hasRun = false
    let failOnStart: Bool
    init(failOnStart: Bool) { self.failOnStart = failOnStart }

    func start(_ request: ResearchStartRequest) async throws -> ResearchAccepted {
        if failOnStart { throw APIError.server(status: 503, message: "Synthetic research failure for UI testing.") }
        query = request.query
        phase = "in_progress"
        polls = 0
        hasRun = true
        return try decoded(ResearchAccepted.self, ["status": "success", "research_id": "synthetic-running"])
    }
    func progress(id: String) async throws -> ResearchProgress {
        if id == "synthetic-history" {
            return try decoded(ResearchProgress.self, ["status": "completed", "progress": 100])
        }
        polls += 1
        if polls >= 8 && phase == "in_progress" { phase = "completed" }
        return try decoded(ResearchProgress.self, ["status": phase, "progress": min(100, polls * 12),
                                                   "log_entry": ["message": "Synthetic progress event", "type": "MILESTONE"]])
    }
    func stop(id: String) async throws { phase = "suspended" }
    func report(id: String) async throws -> ResearchReport {
        if id == "synthetic-running" && phase == "suspended" {
            return try decoded(ResearchReport.self, ["content": "# Synthetic stopped report\n\nThe fixture was stopped.", "sources": []])
        }
        let title = id == "synthetic-history" ? "Synthetic history report" : "Synthetic completed report"
        return try decoded(ResearchReport.self, [
            "content": "# \(title)\n\nThis is a deterministic UI fixture [7].\n\n<script>this is displayed as text</script>",
            "sources": [["url": "https://example.invalid/evidence", "title": "Synthetic evidence link"],
                        ["url": "javascript:alert(1)", "title": "Unsafe fixture URL"]],
            "metadata": ["title": title]
        ])
    }
    func history(offset: Int) async throws -> [ResearchHistoryItem] {
        guard offset == 0 else { return [] }
        var rows: [[String: Any]] = [
            ["id": "synthetic-history", "title": "Synthetic completed research", "query": "Synthetic history question", "mode": "quick", "status": "completed"]
        ]
        if hasRun {
            rows.insert(["id": "synthetic-running", "title": query, "query": query, "mode": "quick", "status": phase], at: 0)
        }
        return try decoded([ResearchHistoryItem].self, rows)
    }
    func signOut() async throws {}
    func disconnect() async {}
}

@MainActor
private final class SyntheticModels: ModelManaging {
    @Published var models: [CuratedModel] = []
    @Published var errorMessage: String?
    @Published var selectedModelID: String?
    @Published private var states: [String: ModelDownloadState] = [:]
    let memoryGB = 96
    private var tasks: [String: Task<Void, Never>] = [:]
    private var attempted = Set<String>()
    private var queue: [CuratedModel] = []
    let temporaryRoot: URL

    init() {
        temporaryRoot = FileManager.default.temporaryDirectory.resolvingSymlinksInPath()
            .appendingPathComponent("Deepdesk-UIHost-\(UUID().uuidString)", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: temporaryRoot, withIntermediateDirectories: true)
            guard let url = Bundle.main.url(forResource: "model-catalog", withExtension: "json") else { throw ModelCatalogError.notBundled }
            models = try JSONDecoder().decode(ModelCatalog.self, from: Data(contentsOf: url)).validated().models
            selectedModelID = models.first?.id
        } catch { errorMessage = error.localizedDescription }
    }
    func state(for model: CuratedModel) -> ModelDownloadState { states[model.id] ?? .available }
    func choose(_ model: CuratedModel) { selectedModelID = model.id }
    func download(_ model: CuratedModel) {
        if states.contains(where: { key, value in
            if case .downloading = value { return key != model.id }
            return false
        }) {
            if !queue.contains(where: { $0.id == model.id }) { queue.append(model) }
            states[model.id] = .queued
            return
        }
        tasks[model.id]?.cancel()
        let shouldFail = model.id == "qwen38-27b-uncensored" && !attempted.contains(model.id)
        attempted.insert(model.id)
        states[model.id] = .downloading(0, model.totalBytes)
        tasks[model.id] = Task { [weak self] in
            for step in 1...10 {
                do { try await Task.sleep(for: .milliseconds(ProcessInfo.processInfo.arguments.contains("--slow-downloads") ? 2000 : 500)) } catch { return }
                guard let self else { return }
                if shouldFail && step == 3 {
                    self.states[model.id] = .failed("Synthetic interrupted download. No network request occurred.")
                    self.startNext()
                    return
                }
                self.states[model.id] = .downloading(model.totalBytes * Int64(step) / 10, model.totalBytes)
            }
            self?.states[model.id] = .installed
            self?.startNext()
        }
    }
    func pause(_ model: CuratedModel) {
        queue.removeAll { $0.id == model.id }
        tasks[model.id]?.cancel()
        states[model.id] = .paused
        startNext()
    }
    private func startNext() {
        guard !queue.isEmpty, !states.values.contains(where: {
            if case .downloading = $0 { return true }; return false
        }) else { return }
        download(queue.removeFirst())
    }
    func verifyForUse(_ model: CuratedModel) async throws -> URL {
        temporaryRoot.appendingPathComponent(model.id)
    }
}

@MainActor
private final class UITestFixtures: ObservableObject {
    let store = ResearchStore()
    let engine = EngineSupervisor()
    let inference = InferenceSupervisor()
    let models = SyntheticModels()
    let identity: LocalIdentityManager
    let service: SyntheticResearchService
    @Published var sourceWasHandled = false
    private var setupInProgress = false

    init() {
        let coordinator = LocalIdentityCoordinator(vault: MemoryVault(), markers: MemoryMarkers(), generate: {
            LocalIdentity(username: "synthetic-only", password: "synthetic-not-a-real-credential-a1")
        })
        identity = LocalIdentityManager(coordinator: coordinator, existingEncryptedData: false, signingCheck: { true })
        service = SyntheticResearchService(failOnStart: ProcessInfo.processInfo.arguments.contains("--research-failure"))
    }
    func bootstrap() async {
        guard identity.disclosureAccepted, !setupInProgress else { return }
        setupInProgress = true
        defer { setupInProgress = false }
        if await identity.prepare() { await store.attach(service: service, displayIdentity: "Synthetic researcher") }
    }
    func activate(_ model: CuratedModel) async {
        do {
            try await store.requireNoActiveResearch()
            models.choose(model)
            store.configureInference(model: model, endpoint: URL(string: "http://127.0.0.1:49152/v1")!, servedModelID: model.repository,
                                     thinking: model.thinkingSupported)
        } catch { store.handle(error) }
    }
}

@main
private struct DeepdeskUITestHost: App {
    @StateObject private var fixture = UITestFixtures()
    private var dark: Bool { ProcessInfo.processInfo.arguments.contains("--dark") }

    var body: some Scene {
        Window("Deepdesk Synthetic UI Test Host", id: "test-host") {
            VStack(spacing: 0) {
                Text("SYNTHETIC UI TEST HOST · No real models, network, Keychain, or research")
                    .font(.caption.bold()).frame(maxWidth: .infinity).padding(8)
                    .background(Color.yellow.opacity(0.2)).accessibilityIdentifier("synthetic-host-banner")
                if fixture.sourceWasHandled {
                    Text("Synthetic source link intercepted; no browser opened.").accessibilityIdentifier("source-intercepted")
                }
                ContentView(store: fixture.store, engine: fixture.engine, models: fixture.models,
                            identity: fixture.identity, inference: fixture.inference,
                            bootstrapAction: fixture.bootstrap, activateModelAction: fixture.activate,
                            deviceEligibility: HardwareEligibility(supported: true, description: "Synthetic supported device"),
                            inferenceStatusOverride: "Synthetic model fixture; no inference process")
            }
            .frame(minWidth: 980, minHeight: 660)
            .preferredColorScheme(dark ? .dark : .light)
            .environment(\.openURL, OpenURLAction { _ in fixture.sourceWasHandled = true; return .handled })
        }
        .windowResizability(.contentMinSize)
        .defaultSize(width: 1180, height: 850)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Research") { fixture.store.newResearch() }.keyboardShortcut("n", modifiers: .command)
            }
        }
    }
}
