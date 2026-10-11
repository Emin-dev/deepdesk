#if os(macOS)
import Foundation
import DeepdeskCore
import Darwin

struct DownloadResumeRecord: Codable {
    let expectedHash: String
    let expectedBytes: Int64
    let etag: String
}

/// A single serial file transfer. Range responses are accepted only with a matching strong ETag.
final class ModelDownloadTransfer: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let artifact: ModelArtifact
    private let allowedHosts: Set<String>
    private let partialURL: URL
    private let resumeURL: URL
    private let onProgress: @Sendable (Int64) -> Void
    private var continuation: CheckedContinuation<URL, Error>?
    private var handle: FileHandle?
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var offset: Int64 = 0
    private var expectedETag: String?
    private var transferError: Error?
    private var lastProgressTime = ContinuousClock.now
    private let lock = NSLock()

    init(artifact: ModelArtifact, allowedHosts: [String], partialURL: URL,
         onProgress: @escaping @Sendable (Int64) -> Void) {
        self.artifact = artifact
        self.allowedHosts = Set(allowedHosts)
        self.partialURL = partialURL
        resumeURL = partialURL.appendingPathExtension("resume.json")
        self.onProgress = onProgress
    }

    func download() async throws -> URL {
        try prepareFile()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                self.continuation = continuation
                let configuration = URLSessionConfiguration.ephemeral
                configuration.urlCache = nil
                configuration.urlCredentialStorage = nil
                configuration.httpCookieStorage = nil
                configuration.httpShouldSetCookies = false
                configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
                configuration.timeoutIntervalForRequest = 60
                configuration.timeoutIntervalForResource = 24 * 60 * 60
                let queue = OperationQueue()
                queue.maxConcurrentOperationCount = 1
                let session = URLSession(configuration: configuration, delegate: self, delegateQueue: queue)
                self.session = session
                var request = URLRequest(url: artifact.url)
                request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
                if offset > 0, let expectedETag {
                    request.setValue("bytes=\(offset)-", forHTTPHeaderField: "Range")
                    request.setValue(expectedETag, forHTTPHeaderField: "If-Range")
                }
                let task = session.dataTask(with: request)
                lock.lock()
                self.task = task
                lock.unlock()
                task.resume()
                if Task.isCancelled { task.cancel() }
            }
        } onCancel: { self.cancel() }
    }

    func cancel() {
        lock.lock()
        let currentTask = task
        lock.unlock()
        currentTask?.cancel()
    }

    private func prepareFile() throws {
        try SafeModelPath.rejectLinks(partialURL)
        try SafeModelPath.rejectLinks(resumeURL)
        try FileManager.default.createDirectory(at: partialURL.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        if let data = try? SafeLocalFile.read(resumeURL, maximumBytes: 16 * 1024),
           let record = try? JSONDecoder().decode(DownloadResumeRecord.self, from: data),
           record.expectedHash == artifact.sha256, record.expectedBytes == artifact.bytes,
           !record.etag.isEmpty, !record.etag.hasPrefix("W/"),
           let attributes = try? FileManager.default.attributesOfItem(atPath: partialURL.path),
           let size = attributes[.size] as? NSNumber, size.int64Value > 0, size.int64Value < artifact.bytes {
            offset = size.int64Value
            expectedETag = record.etag
        } else {
            offset = 0
            expectedETag = nil
        }
        let descriptor = Darwin.open(partialURL.path, O_WRONLY | O_CREAT | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK, 0o600)
        guard descriptor >= 0 else { throw ModelCatalogError.downloadFailed }
        var metadata = stat()
        guard Darwin.fstat(descriptor, &metadata) == 0, metadata.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG), metadata.st_nlink == 1 else {
            Darwin.close(descriptor)
            throw ModelCatalogError.downloadFailed
        }
        handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        if offset == 0 { try handle?.truncate(atOffset: 0) }
        try handle?.seek(toOffset: UInt64(offset))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest,
                    completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        guard let url = request.url, DownloadResponsePolicy.acceptsRedirect(url, allowedHosts: allowedHosts) else {
            transferError = ModelCatalogError.invalidRedirect
            completionHandler(nil)
            return
        }
        completionHandler(request)
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask,
                    didReceive response: URLResponse,
                    completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void) {
        guard let response = response as? HTTPURLResponse else {
            transferError = ModelCatalogError.downloadFailed; completionHandler(.cancel); return
        }
        do {
            let etag = response.value(forHTTPHeaderField: "ETag")
            let action = try DownloadResponsePolicy.validate(status: response.statusCode, offset: offset,
                                                             total: artifact.bytes, expectedETag: expectedETag,
                                                             responseETag: etag,
                                                             contentRange: response.value(forHTTPHeaderField: "Content-Range"))
            if action == .restart {
                offset = 0
                try handle?.truncate(atOffset: 0)
                try handle?.seek(toOffset: 0)
            }
            if let etag, !etag.hasPrefix("W/"), !etag.isEmpty {
                let record = DownloadResumeRecord(expectedHash: artifact.sha256, expectedBytes: artifact.bytes, etag: etag)
                try SafeModelPath.rejectLinks(resumeURL)
                try JSONEncoder().encode(record).write(to: resumeURL, options: .atomic)
            } else if FileManager.default.fileExists(atPath: resumeURL.path) {
                try FileManager.default.removeItem(at: resumeURL)
            }
            completionHandler(.allow)
        } catch {
            transferError = error
            completionHandler(.cancel)
        }
    }

    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        do {
            guard offset + Int64(data.count) <= artifact.bytes else { throw ModelCatalogError.hashMismatch }
            try handle?.write(contentsOf: data)
            offset += Int64(data.count)
            if ContinuousClock.now - lastProgressTime >= .milliseconds(100) || offset == artifact.bytes {
                lastProgressTime = .now
                onProgress(offset)
            }
        } catch {
            transferError = error
            dataTask.cancel()
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        try? handle?.synchronize()
        try? handle?.close()
        handle = nil
        let continuation = self.continuation
        self.continuation = nil
        if let transferError { continuation?.resume(throwing: transferError) }
        else if let error = error as? URLError, error.code == .cancelled { continuation?.resume(throwing: CancellationError()) }
        else if error != nil || offset != artifact.bytes { continuation?.resume(throwing: ModelCatalogError.downloadFailed) }
        else { continuation?.resume(returning: partialURL) }
        session.finishTasksAndInvalidate()
        self.session = nil
    }
}
#endif
