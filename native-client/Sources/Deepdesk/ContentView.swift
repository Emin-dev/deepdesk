#if os(macOS)
import SwiftUI
import DeepdeskCore

struct ContentView<Models: ModelManaging>: View {
    @ObservedObject var store: ResearchStore
    @ObservedObject var engine: EngineSupervisor
    @ObservedObject var models: Models
    @ObservedObject var identity: LocalIdentityManager
    @ObservedObject var inference: InferenceSupervisor
    var bootstrapAction: (@MainActor () async -> Void)?
    var activateModelAction: (@MainActor (CuratedModel) async -> Void)?
    var deviceEligibility = HardwareEligibility.current
    var inferenceStatusOverride: String?
    var presentationNotice: String?
    var windowTitleOverride: String?
    @State private var showModels = false
    @State private var activatingModel = false
    @State private var bootstrapping = false
    @State private var historySelection: String?
    @State private var historySearch = ""
    @State private var showSources = true
    @State private var initialLaunchAttempted = false

    var body: some View {
        NavigationSplitView {
            VStack(spacing: 0) {
                List(selection: $historySelection) {
                    Section("Research history") {
                        ForEach(filteredHistory) { item in
                            VStack(alignment: .leading, spacing: 6) {
                                Text(item.displayTitle).font(.body.weight(.medium)).lineLimit(2)
                                HStack(spacing: 5) {
                                    Circle().fill(phaseColor(item.phase)).frame(width: 5, height: 5)
                                    Text(item.phase.label).font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            .padding(.vertical, 6)
                            .tag(item.id)
                            .accessibilityElement(children: .combine)
                            .accessibilityIdentifier("history.\(item.id)")
                        }
                    }
                    if store.historyHasMore && historySearch.isEmpty {
                        Button("Load more") { Task { await store.refreshHistory(loadMore: true) } }
                            .disabled(store.loadingHistory)
                    }
                }
                .listStyle(.sidebar)
                .overlay {
                    if store.authenticated && store.history.isEmpty && !store.loadingHistory {
                        ContentUnavailableView("Your research starts here", systemImage: "clock",
                                               description: Text("Finished and active research will appear here."))
                            .padding()
                    }
                }
                Divider()
                VStack(alignment: .leading, spacing: 8) {
                    Label("On this Mac", systemImage: "desktopcomputer")
                    Label(engine.state.label, systemImage: engine.state == .ready ? "circle.fill" : "circle")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(18)
            }
            .navigationSplitViewColumnWidth(min: 220, ideal: 260, max: 340)
            .searchable(text: $historySearch, prompt: "Find research")
        } detail: {
            VStack(spacing: 0) {
                if let error = store.errorMessage {
                    messageBanner(error, isError: true)
                }
                if let note = store.connectionNote {
                    messageBanner(note, isError: false)
                }
                if !store.authenticated { welcome }
                else if store.selectedID != nil { researchDetail }
                else { composer }
            }
            .background(Color(nsColor: .textBackgroundColor))
            .navigationTitle(windowTitleOverride ?? (store.selectedID == nil ? "Deepdesk" : "Research"))
            .toolbar {
                ToolbarItemGroup(placement: .primaryAction) {
                    Button { store.newResearch() } label: { Label("New research", systemImage: "square.and.pencil") }
                        .help("New research (⌘N)").disabled(!store.authenticated)
                    Button { Task { await store.refreshHistory() } } label: { Label("Refresh history", systemImage: "arrow.clockwise") }
                        .disabled(!store.authenticated || store.loadingHistory)
                    if store.report != nil {
                        Button { showSources.toggle() } label: { Label("Sources", systemImage: "sidebar.right") }
                            .help("Show or hide source links")
                    }
                    Button { showModels = true } label: { Label("Models", systemImage: "cube") }
                        .disabled(!store.authenticated)
                }
            }
        }
        .navigationSplitViewStyle(.balanced)
        .sheet(isPresented: $showModels) {
            ModelChooserView(manager: models, onUse: { model in Task { await activate(model) } }, loadingModel: activatingModel, operationError: store.errorMessage, eligibility: deviceEligibility, presentationNotice: presentationNotice)
        }
        .onChange(of: historySelection) { _, id in
            if let id, id != store.selectedID, let item = store.history.first(where: { $0.id == id }) {
                store.select(id: id, query: item.query)
            }
        }
        .onChange(of: store.selectedID) { _, id in historySelection = id }
        .onChange(of: inference.state) { _, state in
            if case .failed = state { store.clearInference() }
        }
        .onChange(of: engine.state) { _, state in
            if case .failed = state { Task { await store.disconnectLocally() } }
        }
        .task {
            guard !initialLaunchAttempted else { return }
            initialLaunchAttempted = true
            await bootstrap()
        }
    }

    private var welcome: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 28) {
                Image(systemName: "sparkle.magnifyingglass").font(.system(size: 44, weight: .light)).foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 12) {
                    Text("Room to go deeper.").font(.system(size: 34, weight: .semibold, design: .rounded))
                    Text("Choose a model. Ask a question. Keep the evidence close.")
                        .font(.title3).foregroundStyle(.secondary)
                }
                if !deviceEligibility.supported {
                    Label(deviceEligibility.description, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                }
                if identity.needsDisclosure {
                    VStack(alignment: .leading, spacing: 14) {
                        Text("Private research, protected on this Mac").font(.headline)
                        Text("Deepdesk creates a local research identity and keeps its encryption key in your Mac’s Keychain. No account name or password is needed from you.")
                        Text("The key stays on this Mac. Losing this Keychain key or moving only the encrypted research files to another Mac can make your research inaccessible. Deepdesk cannot reset the key or recover that data.")
                            .foregroundStyle(.secondary)
                        Toggle("I understand how my local research is protected and recovered.", isOn: $identity.disclosureAccepted)
                            .accessibilityIdentifier("onboarding.consent")
                        Button("Set up Deepdesk") { Task { await bootstrap() } }
                            .accessibilityIdentifier("onboarding.continue")
                            .buttonStyle(.borderedProminent)
                            .disabled(bootstrapping || !identity.disclosureAccepted || !deviceEligibility.supported)
                    }
                } else {
                    switch engine.state {
                    case .starting:
                        HStack { ProgressView().controlSize(.small); Text("Starting your local research engine…") }
                    case .missing:
                        Label("This build is missing its bundled research engine.", systemImage: "exclamationmark.triangle")
                        Text("Install a complete Deepdesk build to continue.").foregroundStyle(.secondary)
                    case .failed(let message):
                        Text(message).foregroundStyle(.secondary)
                        Button("Retry local startup") { Task { await bootstrap() } }.buttonStyle(.borderedProminent)
                    default:
                        Button("Continue") { Task { await bootstrap() } }.buttonStyle(.borderedProminent)
                    }
                }
                if let error = identity.errorMessage { Text(error).foregroundStyle(.red).textSelection(.enabled) }
                Divider()
                Text("The app includes its research and inference engines. Models download inside Deepdesk. Web research sends search queries to network services; the selected model runs on your Mac.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            .frame(maxWidth: 640, alignment: .leading)
            .padding(40)
            .frame(maxWidth: .infinity)
        }
    }

    private var composer: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                VStack(alignment: .leading, spacing: 10) {
                    Text("What would you like to understand?")
                        .font(.system(size: 30, weight: .semibold, design: .rounded))
                    Text("A clear question makes room for a useful answer.")
                        .foregroundStyle(.secondary)
                }
                VStack(alignment: .leading, spacing: 12) {
                    Text("Research question").font(.headline)
                    TextEditor(text: $store.query)
                        .font(.body).scrollContentBackground(.hidden)
                        .padding(10)
                        .frame(minHeight: 150, maxHeight: 220)
                        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 12))
                        .overlay(RoundedRectangle(cornerRadius: 12).stroke(.quaternary))
                        .accessibilityLabel("Research question")
                        .accessibilityIdentifier("research.question")
                    HStack {
                        Picker("Depth", selection: $store.mode) {
                            ForEach(ResearchMode.allCases) { Text($0.label).tag($0) }
                        }.pickerStyle(.segmented).frame(width: 210)
                        Spacer()
                        Text("\(store.query.count) / 10,000").font(.caption.monospacedDigit())
                            .foregroundStyle(store.query.count > 10_000 ? Color.red : Color.secondary)
                    }
                }
                configurationSummary
                VStack(alignment: .leading, spacing: 10) {
                    Toggle("Allow this question and follow-up searches to reach external search sites.", isOn: $store.acknowledgedNetworkUse)
                        .accessibilityIdentifier("research.network-consent")
                    Text("The model runs on this Mac. DuckDuckGo and the search services it uses can receive search queries. Websites are contacted to retrieve sources. Network errors or rate limits can interrupt research.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    if store.startingResearch { ProgressView().controlSize(.small) }
                    Button(store.startingResearch ? "Starting…" : "Start research") { Task { await store.startResearch() } }
                        .accessibilityIdentifier("research.start")
                        .buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(!store.canStart)
                        .keyboardShortcut(.return, modifiers: [.command])
                    Spacer()
                    Text("⌘ Return").font(.caption).foregroundStyle(.tertiary)
                }
            }
            .frame(maxWidth: 740, alignment: .leading)
            .padding(36)
            .frame(maxWidth: .infinity)
        }
    }

    private var configurationSummary: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Your model").font(.headline)
                Spacer()
                Button(store.activeModel == nil ? "Choose model" : "Change") { showModels = true }.buttonStyle(.link)
            }
            if let model = store.activeModel {
                Text(model.name).font(.title3.weight(.semibold))
                HStack {
                    Label("On this Mac", systemImage: "desktopcomputer")
                    if store.thinkingEnabled { Label("Thinking on", systemImage: "sparkles") }
                }.font(.caption).foregroundStyle(.secondary)
                Text(inferenceStatusOverride ?? inference.state.label).font(.caption).foregroundStyle(.secondary)
                Label("Sources: DuckDuckGo web search", systemImage: "globe").font(.caption).foregroundStyle(.secondary)
            } else {
                Text("Choose and download a model to start. Splash is selected by default.").foregroundStyle(.secondary)
                if let error = inference.errorMessage { Text(error).font(.caption).foregroundStyle(.red) }
                Button("Choose a model") { showModels = true }.buttonStyle(.borderedProminent)
            }
        }
        .padding(20)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 14))
    }

    private var researchDetail: some View {
        HStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(store.selectedQuery).font(.title.bold()).textSelection(.enabled)
                            .accessibilityIdentifier("research.selected-query")
                        HStack(spacing: 8) {
                            Image(systemName: statusSymbol)
                            Text(store.stoppingResearch ? "Stopping…" : (store.progress?.phase.label ?? "Loading…"))
                                .accessibilityIdentifier("research.phase")
                            if let fraction = store.progress?.fraction, store.hasActiveJob {
                                Text(fraction, format: .percent.precision(.fractionLength(0))).monospacedDigit()
                                    .accessibilityIdentifier("research.progress")
                            }
                        }
                        .font(.callout.weight(.medium))
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .modifier(GlassControlSurface())
                    }
                    if store.hasActiveJob || store.stoppingResearch {
                        VStack(alignment: .leading, spacing: 16) {
                            if let fraction = store.progress?.fraction { ProgressView(value: fraction) }
                            else { ProgressView().controlSize(.small) }
                            if let message = store.progress?.logEntry?.message { Text(message).foregroundStyle(.secondary) }
                            Button(store.stoppingResearch ? "Stopping…" : "Stop research", role: .destructive) {
                                Task { await store.stopResearch() }
                            }
                            .accessibilityIdentifier("research.stop")
                            .disabled(store.stoppingResearch)
                            Text("Research continues if you view another item or close this window.")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if let failure = store.progress?.failureMessage {
                        Label(failure, systemImage: "exclamationmark.triangle").foregroundStyle(.red)
                        if let suggestion = store.progress?.failureSuggestion { Text(suggestion).foregroundStyle(.secondary) }
                    }
                    if let report = store.report, !report.content.isEmpty {
                        Divider()
                        NativeReportView(content: report.content)
                    } else if store.progress?.phase.isTerminal == true {
                        ContentUnavailableView("No report is available", systemImage: "doc.text",
                                               description: Text("The engine did not return a report for this run."))
                        Button("Reload report") {
                            if let id = store.selectedID { store.select(id: id, query: store.selectedQuery) }
                        }
                    }
                }
                .frame(maxWidth: 800, alignment: .leading)
                .padding(36)
                .frame(maxWidth: .infinity)
            }
            if showSources, let report = store.report {
                Divider()
                ScrollView { SourcesView(sources: report.sources) }
                    .frame(minWidth: 230, idealWidth: 280, maxWidth: 320)
                    .background(Color(nsColor: .controlBackgroundColor))
            }
        }
    }

    private var filteredHistory: [ResearchHistoryItem] {
        guard !historySearch.isEmpty else { return store.history }
        return store.history.filter { $0.displayTitle.localizedCaseInsensitiveContains(historySearch) || $0.query.localizedCaseInsensitiveContains(historySearch) }
    }

    private var statusSymbol: String {
        switch store.progress?.phase {
        case .some(.completed): "checkmark.circle"
        case .some(.failed): "exclamationmark.circle"
        case .some(.stopped): "stop.circle"
        case .some(.queued): "clock"
        default: "sparkle.magnifyingglass"
        }
    }

    private func phaseColor(_ phase: JobPhase) -> Color {
        switch phase { case .completed: .green; case .failed: .red; case .running: .accentColor; default: .secondary }
    }

    private func messageBanner(_ text: String, isError: Bool) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: isError ? "exclamationmark.circle" : "info.circle")
            Text(text).textSelection(.enabled)
            Spacer(minLength: 8)
            Button {
                if isError { store.errorMessage = nil } else { store.connectionNote = nil }
            } label: { Image(systemName: "xmark") }
                .buttonStyle(.plain).accessibilityLabel("Dismiss message")
        }
        .font(.callout)
        .foregroundStyle(isError ? Color.red : Color.secondary)
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
    }

    private func bootstrap() async {
        if let bootstrapAction { await bootstrapAction(); return }
        guard !bootstrapping else { return }
        bootstrapping = true
        defer { bootstrapping = false }
        guard deviceEligibility.supported else { return }
        guard await identity.prepare(), let coordinator = identity.coordinator else { return }
        await store.disconnectLocally()
        if await engine.start(), let nonce = engine.instanceNonce {
            await store.connectManaged(port: engine.port, expectedInstance: nonce, identity: coordinator)
            if store.authenticated { showModels = true }
        }
    }

    private func activate(_ model: CuratedModel) async {
        if let activateModelAction { await activateModelAction(model); showModels = false; return }
        guard !activatingModel else { return }
        activatingModel = true
        store.busy = true
        defer { activatingModel = false; store.busy = false }
        do { try await store.requireNoActiveResearch() }
        catch { store.handle(error); return }
        do {
            let target = try await models.verifyForUse(model)
            store.clearInference()
            let connection = try await inference.start(model: model, targetDirectory: target)
            guard await engine.start(inference: connection), let nonce = engine.instanceNonce,
                  let coordinator = identity.coordinator else { throw APIError.connectionUnavailable }
            await store.connectManaged(port: engine.port, expectedInstance: nonce, identity: coordinator)
            guard store.authenticated else { throw IdentityError.reconciliationRequired }
            store.configureInference(model: model, endpoint: connection.endpoint, servedModelID: connection.modelID, thinking: model.thinkingSupported)
            showModels = false
        } catch { store.errorMessage = error.localizedDescription }
    }
}
#endif
