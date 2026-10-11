#if os(macOS)
import SwiftUI
import DeepdeskCore

struct ModelChooserView: View {
    @ObservedObject var manager: ModelManager
    let onUse: (CuratedModel) -> Void
    var loadingModel = false
    var operationError: String?
    private let eligibility = HardwareEligibility.current

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Choose your model").font(.largeTitle.bold())
                    Text("Download once. Think and research on this Mac.")
                        .font(.title3).foregroundStyle(.secondary)
                    Text("Weights come from the listed publisher on Hugging Face. Deepdesk verifies every file before use. Web research still sends search queries to search services.")
                        .font(.callout).foregroundStyle(.secondary)
                }
                if !eligibility.supported {
                    Label(eligibility.description, systemImage: "exclamationmark.triangle").foregroundStyle(.orange)
                }
                if let error = manager.errorMessage {
                    Label(error, systemImage: "exclamationmark.circle").foregroundStyle(.red)
                }
                if let operationError { Text(operationError).foregroundStyle(.red).textSelection(.enabled) }
                ForEach(manager.models) { model in modelCard(model) }
                Text("Models share a verified draft component. It is downloaded only once. Your installed models are checked again before the inference engine opens them.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding(32)
        }
        .frame(minWidth: 580, idealWidth: 700, maxWidth: 900, minHeight: 550)
    }

    private func modelCard(_ model: CuratedModel) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.name).font(.title2.bold())
                    Text(model.summary).foregroundStyle(.secondary)
                }
                Spacer()
                if model.thinkingSupported {
                    Label("Thinking", systemImage: "sparkles").font(.caption.weight(.medium))
                        .padding(.horizontal, 10).padding(.vertical, 7).modifier(GlassControlSurface())
                }
            }
            HStack(spacing: 18) {
                Label(ByteCountFormatter.string(fromByteCount: model.totalBytes, countStyle: .file), systemImage: "arrow.down.circle")
                Label("\(model.minimumMemoryGB) GB+ memory", systemImage: "memorychip")
                Link(model.licenseName, destination: model.licenseURL)
            }.font(.caption).foregroundStyle(.secondary)
            Text("Publisher: \(model.repository)").font(.caption).foregroundStyle(.secondary)
            if let warning = model.contentWarning { Text(warning).font(.caption).foregroundStyle(.secondary) }
            if manager.memoryGB < model.minimumMemoryGB {
                Text("This Mac has \(manager.memoryGB) GB of unified memory. This model requires at least \(model.minimumMemoryGB) GB.")
                    .font(.caption).foregroundStyle(.orange)
            }
            switch manager.state(for: model) {
            case .available:
                Button("Download model") { manager.download(model) }
                    .buttonStyle(.borderedProminent)
                    .disabled(!eligibility.supported || manager.memoryGB < model.minimumMemoryGB)
            case .queued:
                HStack { Text("Queued").foregroundStyle(.secondary); Spacer(); Button("Cancel") { manager.pause(model) } }
            case .downloading(let completed, let total):
                ProgressView(value: Double(completed), total: Double(total))
                HStack {
                    Text("\(ByteCountFormatter.string(fromByteCount: completed, countStyle: .file)) of \(ByteCountFormatter.string(fromByteCount: total, countStyle: .file))")
                        .font(.caption).monospacedDigit().foregroundStyle(.secondary)
                    Spacer()
                    Button("Pause") { manager.pause(model) }
                }
            case .paused:
                HStack { Text("Paused").foregroundStyle(.secondary); Spacer(); Button("Resume download") { manager.download(model) } }
            case .verifying:
                HStack { ProgressView().controlSize(.small); Text("Verifying model files…").foregroundStyle(.secondary) }
            case .installed:
                HStack {
                    Label("Downloaded", systemImage: "checkmark.circle").foregroundStyle(.secondary)
                    Spacer()
                    Button(loadingModel ? "Loading…" : "Use this model") {
                        manager.choose(model)
                        onUse(model)
                    }.buttonStyle(.borderedProminent).disabled(loadingModel || !eligibility.supported)
                }
            case .failed(let message):
                Text(message).font(.caption).foregroundStyle(.red)
                Button("Retry download") { manager.download(model) }.disabled(!eligibility.supported)
            }
        }
        .padding(22)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 18))
        .overlay(RoundedRectangle(cornerRadius: 18).stroke(.quaternary))
    }
}
#endif
