#if os(macOS)
import Foundation
import SwiftUI
import Darwin
import DeepdeskCore

@MainActor
final class EngineSupervisor: ObservableObject {
    enum State: Equatable {
        case stopped, missing, starting, ready, stopping, failed(String)
        var label: String {
            switch self {
            case .stopped: "Stopped"
            case .missing: "Bundled engine not installed"
            case .starting: "Starting local engine…"
            case .ready: "Local engine connected"
            case .stopping: "Stopping local engine…"
            case .failed: "Local engine needs attention"
            }
        }
    }

    @Published private(set) var state: State = .stopped
    private(set) var port = 5000
    private(set) var instanceNonce: String?
    private var process: Process?
    private var stdoutPipe: Pipe?
    private var stderrPipe: Pipe?
    private var launchID = UUID()
    private var configuredInferenceKey: String?

    var ownsRunningProcess: Bool { process?.isRunning == true }
    var bundledEngineURL: URL {
        Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/DeepdeskEngine.app/Contents/MacOS/DeepdeskEngine")
    }

    func start(inference: InferenceConnection? = nil) async -> Bool {
        if state == .ready && ownsRunningProcess && configuredInferenceKey == inference?.apiKey { return true }
        guard state != .starting && state != .stopping else { return false }
        guard FileManager.default.isExecutableFile(atPath: bundledEngineURL.path) else {
            state = .missing
            return false
        }
        await stopAndWait()
        guard !ownsRunningProcess else { return false }
        state = .starting
        let id = UUID()
        launchID = id
        let nonce = UUID().uuidString.replacingOccurrences(of: "-", with: "") + UUID().uuidString.replacingOccurrences(of: "-", with: "")
        instanceNonce = nonce
        port = Int.random(in: 49152...65535)
        do {
            let support = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                                      appropriateFor: nil, create: true)
            let data = support.appendingPathComponent("Deepdesk/Engine", isDirectory: true)
            try SafeModelPath.rejectLinks(data)
            try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true,
                                                     attributes: [.posixPermissions: 0o700])
            let child = Process()
            child.executableURL = bundledEngineURL
            child.arguments = []
            child.currentDirectoryURL = data
            // Start with an allowlist, never forward API keys, Python paths, or arbitrary parent environment.
            var environment: [String: String] = [
                "HOME": NSHomeDirectory(), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "TMPDIR": NSTemporaryDirectory(), "LANG": "en_US.UTF-8",
                "LDR_WEB_HOST": "127.0.0.1", "LDR_WEB_PORT": "\(port)",
                "LDR_DATA_DIR": data.path, "LDR_WEB_USE_HTTPS": "false",
                "LDR_APP_DEBUG": "false", "LDR_LOGURU_DIAGNOSE": "false",
                "LDR_ENABLE_FILE_LOGGING": "false", "LDR_BOOTSTRAP_ALLOW_UNENCRYPTED": "false",
                "PYTHONDONTWRITEBYTECODE": "1", "DEEPDESK_INSTANCE_NONCE": nonce
            ]
            if let inference {
                guard inference.endpoint.scheme == "http", inference.endpoint.host == "127.0.0.1" else {
                    state = .failed("The managed inference endpoint is invalid.")
                    return false
                }
                // Managed wrapper injects the key into the provider in memory, outside upstream setting snapshots.
                environment["DEEPDESK_INFERENCE_MODEL"] = inference.modelID
                environment["DEEPDESK_INFERENCE_URL"] = inference.endpoint.absoluteString
                environment["DEEPDESK_INFERENCE_API_KEY"] = inference.apiKey
                environment["LDR_LLM_REQUIRE_LOCAL_ENDPOINT"] = "true"
                environment["LDR_EMBEDDINGS_REQUIRE_LOCAL"] = "true"
            }
            if let user = ProcessInfo.processInfo.environment["USER"] { environment["USER"] = user }
            child.environment = environment
            let stdout = Pipe()
            let stderr = Pipe()
            child.standardOutput = stdout
            child.standardError = stderr
            for pipe in [stdout, stderr] {
                pipe.fileHandleForReading.readabilityHandler = { handle in
                    // Continuously drain without saving or displaying potentially sensitive engine logs.
                    if handle.availableData.isEmpty { handle.readabilityHandler = nil }
                }
            }
            stdoutPipe = stdout
            stderrPipe = stderr
            child.terminationHandler = { [weak self] child in
                let status = child.terminationStatus
                Task { @MainActor in self?.didTerminate(id: id, status: status) }
            }
            process = child
            try child.run()
            let transport = EphemeralHTTPTransport()
            let endpoint = try LocalEndpoint(port: port)
            let deadline = ContinuousClock.now + .seconds(120)
            while ContinuousClock.now < deadline {
                guard id == launchID, child.isRunning else {
                    await transport.invalidate()
                    if state == .starting { state = .failed("The bundled engine exited during startup. Retry local startup or reinstall a complete verified Deepdesk build.") }
                    return false
                }
                do {
                    var request = URLRequest(url: try endpoint.url(path: "/api/v1/health"))
                    request.timeoutInterval = 2
                    let response = try await transport.send(request)
                    if response.header("X-Deepdesk-Instance") != nonce {
                        await transport.invalidate()
                        await stopAndWait()
                        state = .failed("Another service is using the chosen port. No credentials were sent. Try starting the engine again.")
                        return false
                    }
                    if response.status == 200,
                       let value = try? JSONDecoder().decode(JSONValue.self, from: response.data),
                       value["status"]?.string == "ok", child.isRunning, id == launchID {
                        await transport.invalidate()
                        configuredInferenceKey = inference?.apiKey
                        state = .ready
                        return true
                    }
                } catch { /* Not ready yet. Do not treat liveness as model/research validation. */ }
                do { try await Task.sleep(for: .seconds(1)) }
                catch { await transport.invalidate(); await stopAndWait(); return false }
            }
            await transport.invalidate()
            await stopAndWait()
            state = .failed("The local engine did not become ready within two minutes. It may be missing a runtime dependency. No research was started.")
        } catch {
            await stopAndWait()
            state = .failed("The bundled engine could not launch. Check that this build includes its verified runtime and that the app is installed in a writable user account.")
        }
        return false
    }

    func stopAndWait() async {
        guard let child = process else { return }
        launchID = UUID()
        state = .stopping
        if child.isRunning { child.terminate() }
        let deadline = ContinuousClock.now + .seconds(12)
        while child.isRunning && ContinuousClock.now < deadline {
            try? await Task.sleep(for: .milliseconds(100))
        }
        if child.isRunning {
            // Only this exact owned child is eligible; never inspect or kill a port's other listener.
            _ = Darwin.kill(child.processIdentifier, SIGKILL)
            let killDeadline = ContinuousClock.now + .seconds(3)
            while child.isRunning && ContinuousClock.now < killDeadline {
                try? await Task.sleep(for: .milliseconds(100))
            }
        }
        guard !child.isRunning else {
            state = .failed("The previous research engine has not exited. Retry shutdown before starting another engine.")
            return
        }
        stdoutPipe?.fileHandleForReading.readabilityHandler = nil
        stderrPipe?.fileHandleForReading.readabilityHandler = nil
        stdoutPipe = nil
        stderrPipe = nil
        process = nil
        instanceNonce = nil
        configuredInferenceKey = nil
        state = .stopped
    }

    private func didTerminate(id: UUID, status: Int32) {
        guard id == launchID else { return }
        stdoutPipe?.fileHandleForReading.readabilityHandler = nil
        stderrPipe?.fileHandleForReading.readabilityHandler = nil
        process = nil
        instanceNonce = nil
        state = .failed("The local engine stopped (exit \(status)). Your stored research remains in its local data folder. Restart the engine and sign in again.")
    }
}
#endif
