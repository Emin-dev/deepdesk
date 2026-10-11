#if os(macOS)
import Foundation
import SwiftUI
import DeepdeskCore

@MainActor
final class ResearchStore: ObservableObject {
    @Published var username: String?
    @Published var busy = false
    @Published var loadingHistory = false
    @Published var startingResearch = false
    @Published var stoppingResearch = false
    @Published var errorMessage: String?
    @Published var connectionNote: String?
    @Published var history: [ResearchHistoryItem] = []
    @Published var historyHasMore = false
    @Published var selectedID: String?
    @Published var selectedQuery = ""
    @Published var progress: ResearchProgress?
    @Published var report: ResearchReport?
    @Published var query = ""
    @Published var mode: ResearchMode = .quick
    @Published var requireLocalModels = true
    @Published var privateSourcesOnly = false
    @Published var acknowledgedNetworkUse = false
    @Published var port = 5000
    @Published var activeModel: CuratedModel?
    @Published var activeInferenceEndpoint: URL?
    private var servedModelID: String?
    @Published var thinkingEnabled = true

    private var api: (any ResearchService)?
    private var pollingTask: Task<Void, Never>?
    private var selectionTask: Task<Void, Never>?
    private var sessionGeneration = UUID()
    private var selectionGeneration = UUID()

    init() {}

    /// Allows a dedicated host to supply an isolated service; the release entrypoint uses connectManaged.
    func attach(service: any ResearchService, displayIdentity: String) async {
        await disconnectLocally()
        api = service
        username = displayIdentity
        await loadSession()
    }

    var authenticated: Bool { username != nil }
    var hasActiveJob: Bool { progress?.phase.isActive == true }
    var canStart: Bool {
        authenticated && !startingResearch && !busy &&
        !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && query.count <= 10_000 &&
        activeModel != nil && activeInferenceEndpoint != nil && (privateSourcesOnly || acknowledgedNetworkUse)
    }

    func connectManaged(port: Int, expectedInstance: String, identity: LocalIdentityCoordinator) async {
        await disconnectLocally()
        do {
            self.port = port
            let client = ResearchAPI(endpoint: try LocalEndpoint(port: port), expectedInstance: expectedInstance)
            api = client
            // The coordinator returns the exact identity already confirmed by the API adapter.
            // Do not replace it with a second, independently returned account name.
            username = try await identity.authenticate(using: client)
            await loadSession()
        } catch { handle(error) }
    }

    func configureInference(model: CuratedModel, endpoint: URL, servedModelID: String, thinking: Bool) {
        guard endpoint.scheme == "http", endpoint.host == "127.0.0.1", endpoint.path == "/v1" else { return }
        activeModel = model
        activeInferenceEndpoint = endpoint
        self.servedModelID = servedModelID
        thinkingEnabled = thinking && model.thinkingSupported
    }

    func clearInference() { activeModel = nil; activeInferenceEndpoint = nil; servedModelID = nil }

    private func loadSession() async {
        await refreshHistory()
    }

    func refreshHistory(loadMore: Bool = false) async {
        guard let api, authenticated, !loadingHistory else { return }
        loadingHistory = true
        let generation = sessionGeneration
        defer { if generation == sessionGeneration { loadingHistory = false } }
        do {
            let page = try await api.history(offset: loadMore ? history.count : 0)
            guard generation == sessionGeneration else { return }
            if loadMore {
                let known = Set(history.map(\.id))
                history.append(contentsOf: page.filter { !known.contains($0.id) })
            } else { history = page }
            historyHasMore = page.count == 50
        } catch { if generation == sessionGeneration { handle(error) } }
    }

    func requireNoActiveResearch() async throws {
        guard let api, authenticated else { throw APIError.unauthorized }
        var offset = 0
        while true {
            let page = try await api.history(offset: offset)
            if page.contains(where: { !$0.phase.isTerminal }) {
                throw APIError.invalidInput("Stop all active or queued research before switching models. Only one model is kept in memory.")
            }
            if page.count < 50 { return }
            offset += page.count
        }
    }

    func newResearch() {
        selectionTask?.cancel()
        pollingTask?.cancel()
        selectionGeneration = UUID()
        selectedID = nil
        selectedQuery = ""
        progress = nil
        report = nil
        stoppingResearch = false
        connectionNote = nil
    }

    func startResearch() async {
        guard let api, canStart else { return }
        startingResearch = true
        errorMessage = nil
        let generation = sessionGeneration
        var request = ResearchStartRequest(query: query.trimmingCharacters(in: .whitespacesAndNewlines), mode: mode)
        request.modelProvider = "openai_endpoint"
        request.model = servedModelID
        request.customEndpoint = activeInferenceEndpoint?.absoluteString
        request.searchEngine = "ddg"
        request.strategy = "source-based"
        request.llmRequireLocalEndpoint = true
        request.embeddingsRequireLocal = true
        if privateSourcesOnly { request.policyEgressScope = "private_only" }
        defer { if generation == sessionGeneration { startingResearch = false } }
        do {
            let accepted = try await api.start(request)
            guard generation == sessionGeneration else { return }
            let startedQuery = request.query
            query = ""
            await refreshHistory()
            select(id: accepted.researchID, query: startedQuery)
        } catch {
            guard generation == sessionGeneration else { return }
            handle(error)
            if (error as? APIError) == .connectionUnavailable {
                errorMessage = "The start request was interrupted. It may have started on the engine. Refresh History before starting the same question again."
                await refreshHistory()
            }
        }
    }

    func select(id: String, query: String) {
        selectionTask?.cancel()
        pollingTask?.cancel()
        selectedID = id
        selectedQuery = query
        progress = nil
        report = nil
        stoppingResearch = false
        connectionNote = nil
        let selection = UUID()
        selectionGeneration = selection
        selectionTask = Task { [weak self] in
            await self?.loadSelection(id: id, selection: selection)
        }
    }

    private func loadSelection(id: String, selection: UUID) async {
        guard let api else { return }
        do {
            let value = try await api.progress(id: id)
            guard !Task.isCancelled, selection == selectionGeneration else { return }
            progress = value
            if value.phase.isTerminal {
                await loadReport(id: id, selection: selection)
            } else { beginPolling(id: id, selection: selection) }
        } catch {
            guard !Task.isCancelled, selection == selectionGeneration else { return }
            handle(error)
            if (error as? APIError) != .unauthorized { beginPolling(id: id, selection: selection) }
        }
    }

    private func beginPolling(id: String, selection: UUID) {
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            var backoff = 2
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(backoff)) } catch { return }
                guard let self, let api = self.api, selection == self.selectionGeneration else { return }
                do {
                    let value = try await api.progress(id: id)
                    guard !Task.isCancelled, selection == self.selectionGeneration else { return }
                    self.progress = value
                    self.connectionNote = nil
                    backoff = 2
                    if value.phase.isTerminal {
                        self.stoppingResearch = false
                        await self.loadReport(id: id, selection: selection)
                        await self.refreshHistory()
                        return
                    }
                } catch {
                    guard !Task.isCancelled, selection == self.selectionGeneration else { return }
                    if (error as? APIError) == .unauthorized {
                        self.handle(error)
                        return
                    }
                    self.connectionNote = "Connection interrupted. Your research ID is preserved; reconnecting in the background."
                    backoff = min(backoff * 2, 30)
                }
            }
        }
    }

    private func loadReport(id: String, selection: UUID) async {
        guard let api else { return }
        do {
            let value = try await api.report(id: id)
            guard !Task.isCancelled, selection == selectionGeneration else { return }
            report = value
        } catch {
            guard !Task.isCancelled, selection == selectionGeneration else { return }
            // A stopped or failed run may have no report yet; keep its real terminal status visible.
            if progress?.phase == .completed { handle(error) }
        }
    }

    func stopResearch() async {
        guard let api, let id = selectedID, !stoppingResearch, hasActiveJob else { return }
        let selection = selectionGeneration
        stoppingResearch = true
        do {
            try await api.stop(id: id)
            guard selection == selectionGeneration else { return }
            // Acknowledgement is not completion. Continue polling until suspended/completed/failed.
            beginPolling(id: id, selection: selection)
        } catch {
            guard selection == selectionGeneration else { return }
            stoppingResearch = false
            handle(error)
        }
    }

    func signOut() async {
        guard let api else { return }
        do { try await api.signOut() }
        catch { handle(error) }
        await disconnectLocally()
    }

    func disconnectLocally() async {
        sessionGeneration = UUID()
        selectionGeneration = UUID()
        pollingTask?.cancel()
        selectionTask?.cancel()
        let oldAPI = api
        api = nil
        username = nil
        activeModel = nil
        activeInferenceEndpoint = nil
        history = []
        historyHasMore = false
        selectedID = nil
        selectedQuery = ""
        query = ""
        progress = nil
        report = nil
        busy = false
        loadingHistory = false
        startingResearch = false
        stoppingResearch = false
        connectionNote = nil
        await oldAPI?.disconnect()
    }

    func handle(_ error: Error) {
        if error is CancellationError { return }
        errorMessage = error.localizedDescription
        if (error as? APIError) == .unauthorized || (error as? APIError) == .csrfExpired {
            pollingTask?.cancel()
            selectionTask?.cancel()
            sessionGeneration = UUID()
            selectionGeneration = UUID()
            username = nil
            history = []
            report = nil
            progress = nil
            selectedID = nil
            selectedQuery = ""
            busy = false
            loadingHistory = false
            startingResearch = false
            stoppingResearch = false
        }
    }
}
#endif
