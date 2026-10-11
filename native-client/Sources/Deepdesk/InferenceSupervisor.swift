#if os(macOS)
import Foundation
import SwiftUI
import Darwin
import DeepdeskCore

struct InferenceConnection: Sendable {
    let endpoint: URL
    let apiKey: String
    let modelID: String
}

@MainActor
final class InferenceSupervisor: ObservableObject {
    enum State: Equatable {
        case stopped, loading, ready(String), stopping, failed(String)
        var label: String {
            switch self {
            case .stopped: "Model not loaded"
            case .loading: "Loading model into memory…"
            case .ready: "Model ready on this Mac"
            case .stopping: "Unloading model…"
            case .failed: "Model needs attention"
            }
        }
    }
    @Published private(set) var state: State = .stopped
    private var process: Process?
    private var output: [Pipe] = []
    private var launchID = UUID()
    private var ownedProcessGroup: Int32?
    private(set) var connection: InferenceConnection?
    var ownsRunningProcess: Bool { process?.isRunning == true || ownedGroupIsAlive }
    private var ownedGroupIsAlive: Bool {
        guard let group = ownedProcessGroup else { return false }
        return Darwin.kill(-group, 0) == 0 || errno == EPERM
    }
    var errorMessage: String? { if case .failed(let message) = state { message } else { nil } }

    func start(model: CuratedModel, targetDirectory: URL) async throws -> InferenceConnection {
        guard HardwareEligibility.current.supported else { throw ModelCatalogError.runtimeUnavailable }
        if case .ready(let id) = state, id == model.id, ownsRunningProcess, let connection { return connection }
        // Never keep two 27B targets resident, even briefly during a switch.
        await stopAndWait()
        guard !ownsRunningProcess else { throw ModelCatalogError.runtimeUnavailable }
        let resources = Bundle.main.bundleURL.appendingPathComponent("Contents/Resources")
        let executable = resources.appendingPathComponent("SplashRuntime/python/bin/python3")
        let script = resources.appendingPathComponent("deepdesk_inference.py")
        guard FileManager.default.isExecutableFile(atPath: executable.path),
              FileManager.default.fileExists(atPath: script.path),
              targetDirectory.lastPathComponent == model.targetDirectory else {
            state = .failed(ModelCatalogError.runtimeUnavailable.localizedDescription)
            throw ModelCatalogError.runtimeUnavailable
        }
        state = .loading
        let id = UUID()
        launchID = id
        let port = Int.random(in: 49152...65535)
        let key = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased() + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        let nonce = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased() + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        let modelsRoot = targetDirectory.deletingLastPathComponent()
        let dataRoot = modelsRoot.deletingLastPathComponent()
        let child = Process()
        child.executableURL = executable
        child.arguments = ["-I", "-B", script.path]
        child.currentDirectoryURL = dataRoot
        child.environment = [
            "HOME": NSHomeDirectory(), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": NSTemporaryDirectory(),
            "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1",
            "DEEPDESK_MODEL_ID": model.id, "DEEPDESK_MODELS_ROOT": modelsRoot.path,
            "DEEPDESK_DATA_DIR": dataRoot.path, "DEEPDESK_INFERENCE_PORT": "\(port)",
            "DEEPDESK_INFERENCE_NONCE": nonce, "SPLASH_API_KEY": key
        ]
        let stdout = Pipe(), stderr = Pipe()
        output = [stdout, stderr]
        child.standardOutput = stdout
        child.standardError = stderr
        for pipe in output {
            pipe.fileHandleForReading.readabilityHandler = { handle in
                if handle.availableData.isEmpty { handle.readabilityHandler = nil }
            }
        }
        child.terminationHandler = { [weak self] child in
            let status = child.terminationStatus
            Task { @MainActor in
                guard let self, self.launchID == id else { return }
                self.connection = nil
                if !self.ownedGroupIsAlive { self.process = nil; self.ownedProcessGroup = nil }
                self.state = .failed("The model engine stopped (exit \(status)). Retry loading the selected model.")
            }
        }
        process = child
        do {
            try child.run()
            let transport = EphemeralHTTPTransport()
            let endpoint = try LocalEndpoint(port: port)
            let deadline = ContinuousClock.now + .seconds(600)
            while ContinuousClock.now < deadline {
                try Task.checkCancellation()
                if child.isRunning, Darwin.getpgid(child.processIdentifier) == child.processIdentifier {
                    ownedProcessGroup = child.processIdentifier
                }
                guard child.isRunning, launchID == id else { throw ModelCatalogError.runtimeUnavailable }
                do {
                    var ready = URLRequest(url: try endpoint.url(path: "/ready"))
                    ready.timeoutInterval = 3
                    // Token-free readiness verifies the owned wrapper before any API secret is sent.
                    let response = try await transport.send(ready)
                    guard response.header("X-Deepdesk-Inference-Instance") == nonce else { throw APIError.instanceMismatch }
                    if response.status == 200 {
                        var request = URLRequest(url: try endpoint.url(path: "/v1/models"))
                        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
                        let models = try await transport.send(request)
                        guard models.header("X-Deepdesk-Inference-Instance") == nonce else { throw APIError.instanceMismatch }
                        if models.status == 200,
                           let body = try? JSONDecoder().decode(JSONValue.self, from: models.data),
                           body["data"]?.array?.contains(where: { $0["id"]?.string == model.repository }) == true {
                            await transport.invalidate()
                            let connection = InferenceConnection(endpoint: try endpoint.url(path: "/v1"), apiKey: key, modelID: model.repository)
                            self.connection = connection
                            state = .ready(model.id)
                            return connection
                        }
                    }
                } catch let error as APIError where error == .instanceMismatch {
                    await transport.invalidate()
                    throw error
                } catch { /* The model can need time to load; no ready state before exact model verification. */ }
                try await Task.sleep(for: .seconds(2))
            }
            await transport.invalidate()
            throw APIError.invalidInput("The selected model did not become ready within ten minutes. Check this Mac’s available memory and retry.")
        } catch {
            await stopAndWait()
            state = .failed(error.localizedDescription)
            throw error
        }
    }

    func stopAndWait() async {
        connection = nil
        guard let child = process else { state = .stopped; return }
        launchID = UUID()
        state = .stopping
        if child.isRunning { child.terminate() }
        let deadline = ContinuousClock.now + .seconds(20)
        while (child.isRunning || ownedGroupIsAlive) && ContinuousClock.now < deadline { try? await Task.sleep(for: .milliseconds(100)) }
        if child.isRunning {
            // Revalidate the live owned leader at the moment of group escalation; cached IDs are not authority.
            if Darwin.getpgid(child.processIdentifier) == child.processIdentifier {
                ownedProcessGroup = child.processIdentifier
                _ = Darwin.kill(-child.processIdentifier, SIGKILL)
            } else { _ = Darwin.kill(child.processIdentifier, SIGKILL) }
        } else if ownedGroupIsAlive {
            state = .failed("The model leader exited before its child group could be verified as stopped. Deepdesk will not load another model or signal a potentially reused process group.")
            return
        }
        let killDeadline = ContinuousClock.now + .seconds(3)
        while (child.isRunning || ownedGroupIsAlive) && ContinuousClock.now < killDeadline { try? await Task.sleep(for: .milliseconds(100)) }
        guard !child.isRunning, !ownedGroupIsAlive else {
            state = .failed("The previous model process has not exited. Deepdesk will not load a second model until shutdown is confirmed.")
            return
        }
        for pipe in output { pipe.fileHandleForReading.readabilityHandler = nil }
        output = []
        process = nil
        ownedProcessGroup = nil
        state = .stopped
    }
}
#endif
