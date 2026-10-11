#if os(macOS)
import Foundation
import SwiftUI
import CryptoKit
import Darwin
import DeepdeskCore

enum ModelDownloadState: Equatable {
    case available, queued, downloading(Int64, Int64), paused, verifying, installed, failed(String)
}

@MainActor
protocol ModelManaging: ObservableObject {
    var models: [CuratedModel] { get }
    var errorMessage: String? { get }
    var selectedModelID: String? { get }
    var memoryGB: Int { get }
    func state(for model: CuratedModel) -> ModelDownloadState
    func choose(_ model: CuratedModel)
    func download(_ model: CuratedModel)
    func pause(_ model: CuratedModel)
    func verifyForUse(_ model: CuratedModel) async throws -> URL
}

@MainActor
final class ModelManager: ModelManaging {
    typealias DownloadState = ModelDownloadState
    @Published private(set) var models: [CuratedModel] = []
    @Published private(set) var states: [String: DownloadState] = [:]
    @Published private(set) var errorMessage: String?
    @Published var selectedModelID: String?
    @Published var thinkingEnabled = true
    private var downloadTask: Task<Void, Never>?
    private var activeTransfer: ModelDownloadTransfer?
    private var activeDownloadID: String?
    private var queue: [CuratedModel] = []

    init() {
        do {
            let catalog = try BundledModelCatalog.load(applicationBundleURL: Bundle.main.bundleURL)
            models = catalog.models
            for model in models {
                states[model.id] = (try? hasAllFiles(model)) == true ? .installed : .available
            }
            let previous = UserDefaults.standard.string(forKey: "selectedCuratedModel")
            selectedModelID = models.contains(where: { $0.id == previous }) ? previous : models.first?.id
        } catch { errorMessage = error.localizedDescription }
    }

    var selectedModel: CuratedModel? { models.first { $0.id == selectedModelID } }
    var memoryGB: Int { Int(ProcessInfo.processInfo.physicalMemory / (1024 * 1024 * 1024)) }
    func state(for model: CuratedModel) -> DownloadState { states[model.id] ?? .available }

    func choose(_ model: CuratedModel) {
        selectedModelID = model.id
        thinkingEnabled = model.thinkingSupported
        UserDefaults.standard.set(model.id, forKey: "selectedCuratedModel")
    }

    func download(_ model: CuratedModel) {
        guard activeDownloadID != model.id, !queue.contains(where: { $0.id == model.id }) else { return }
        queue.append(model)
        states[model.id] = .queued
        beginNextDownload()
    }

    func pause(_ model: CuratedModel) {
        if activeDownloadID == model.id { downloadTask?.cancel(); activeTransfer?.cancel() }
        else { queue.removeAll { $0.id == model.id }; states[model.id] = .paused }
    }

    func verifyForUse(_ model: CuratedModel) async throws -> URL {
        states[model.id] = .verifying
        do {
            let folder = try modelDirectory(model)
            for artifact in model.artifacts {
                let file = try SafeModelPath.resolve(root: folder, relativePath: artifact.path)
                let hash = try await Self.sha256(file)
                guard hash == artifact.sha256 else { throw ModelCatalogError.hashMismatch }
            }
            states[model.id] = .installed
            return folder.appendingPathComponent(model.targetDirectory, isDirectory: true)
        } catch {
            states[model.id] = .failed(error.localizedDescription)
            throw error
        }
    }

    private func beginNextDownload() {
        guard activeDownloadID == nil, !queue.isEmpty else { return }
        let model = queue.removeFirst()
        activeDownloadID = model.id
        downloadTask = Task { [weak self] in
            guard let self else { return }
            do {
                let folder = try self.modelDirectory(model)
                let attributes = try FileManager.default.attributesOfFileSystem(forPath: folder.path)
                let available = (attributes[.systemFreeSize] as? NSNumber)?.int64Value ?? 0
                // A model artifact is renamed in-place after verification; reserve an extra 1 GiB for runtime work.
                self.states[model.id] = .verifying
                var verifiedFiles = Set<String>()
                var needed: Int64 = 0
                for artifact in model.artifacts {
                    try Task.checkCancellation()
                    let target = try SafeModelPath.resolve(root: folder, relativePath: artifact.path)
                    if FileManager.default.fileExists(atPath: target.path), try await Self.sha256(target) == artifact.sha256 {
                        verifiedFiles.insert(artifact.path)
                    } else {
                        // Do not credit unverified same-size files or partials against the free-space reserve.
                        needed += artifact.bytes
                    }
                }
                guard available >= needed + 1_073_741_824 else { throw ModelCatalogError.insufficientDiskSpace }
                var finishedBytes: Int64 = 0
                for artifact in model.artifacts {
                    try Task.checkCancellation()
                    let target = try SafeModelPath.resolve(root: folder, relativePath: artifact.path)
                    if verifiedFiles.contains(artifact.path) {
                        finishedBytes += artifact.bytes
                        continue
                    }
                    let base = finishedBytes
                    let partial = target.appendingPathExtension("partial")
                    let transfer = ModelDownloadTransfer(artifact: artifact, allowedHosts: model.downloadHosts,
                                                         partialURL: partial) { [weak self] bytes in
                        Task { @MainActor in
                            guard let self, self.activeDownloadID == model.id else { return }
                            self.states[model.id] = .downloading(base + bytes, model.totalBytes)
                        }
                    }
                    self.activeTransfer = transfer
                    let downloaded = try await transfer.download()
                    self.activeTransfer = nil
                    try Task.checkCancellation()
                    self.states[model.id] = .verifying
                    guard try await Self.sha256(downloaded) == artifact.sha256 else { throw ModelCatalogError.hashMismatch }
                    // Only verified bytes become the installed artifact, with an atomic same-volume rename.
                    if FileManager.default.fileExists(atPath: target.path) {
                        _ = try FileManager.default.replaceItemAt(target, withItemAt: downloaded)
                    } else { try FileManager.default.moveItem(at: downloaded, to: target) }
                    let resume = partial.appendingPathExtension("resume.json")
                    if FileManager.default.fileExists(atPath: resume.path) { try FileManager.default.removeItem(at: resume) }
                    finishedBytes += artifact.bytes
                }
                self.states[model.id] = .installed
            } catch is CancellationError { self.states[model.id] = .paused }
            catch { self.states[model.id] = .failed(error.localizedDescription) }
            self.activeTransfer = nil
            self.activeDownloadID = nil
            self.downloadTask = nil
            self.beginNextDownload()
        }
    }

    private func modelDirectory(_ model: CuratedModel) throws -> URL {
        let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                  appropriateFor: nil, create: true)
        let folder = support.appendingPathComponent("Deepdesk/Models", isDirectory: true)
        try SafeModelPath.rejectLinks(folder)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        return folder
    }

    private func hasAllFiles(_ model: CuratedModel) throws -> Bool {
        let folder = try modelDirectory(model)
        return model.artifacts.allSatisfy { artifact in
            guard let file = try? SafeModelPath.resolve(root: folder, relativePath: artifact.path),
                  let attrs = try? FileManager.default.attributesOfItem(atPath: file.path),
                  let size = attrs[.size] as? NSNumber else { return false }
            return size.int64Value == artifact.bytes
        }
    }

    nonisolated private static func sha256(_ url: URL) async throws -> String {
        let task = Task.detached(priority: .utility) {
            try SafeModelPath.rejectLinks(url)
            let descriptor = Darwin.open(url.path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
            guard descriptor >= 0 else { throw ModelCatalogError.hashMismatch }
            var metadata = stat()
            guard Darwin.fstat(descriptor, &metadata) == 0, metadata.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG) else {
                Darwin.close(descriptor)
                throw ModelCatalogError.hashMismatch
            }
            let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
            defer { try? handle.close() }
            var hash = SHA256()
            while let data = try handle.read(upToCount: 4 * 1024 * 1024), !data.isEmpty {
                try Task.checkCancellation()
                hash.update(data: data)
            }
            return hash.finalize().map { String(format: "%02x", $0) }.joined()
        }
        return try await withTaskCancellationHandler { try await task.value } onCancel: { task.cancel() }
    }
}
#endif
