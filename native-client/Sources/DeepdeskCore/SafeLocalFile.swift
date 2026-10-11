import Foundation
#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#endif

public enum SafeLocalFile {
    /// Bounded, non-blocking metadata read. Rejects links, devices, FIFOs, and oversized files.
    public static func read(_ url: URL, maximumBytes: Int) throws -> Data {
        guard maximumBytes > 0 else { throw ModelCatalogError.invalidManifest }
        try SafeModelPath.rejectLinks(url)
        let descriptor = open(url.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard descriptor >= 0 else { throw ModelCatalogError.invalidManifest }
        var metadata = stat()
        guard fstat(descriptor, &metadata) == 0,
              metadata.st_mode & mode_t(S_IFMT) == mode_t(S_IFREG), metadata.st_nlink == 1,
              metadata.st_size >= 0, metadata.st_size <= maximumBytes else {
            close(descriptor)
            throw ModelCatalogError.invalidManifest
        }
        let handle = FileHandle(fileDescriptor: descriptor, closeOnDealloc: true)
        defer { try? handle.close() }
        let data = try handle.read(upToCount: maximumBytes + 1) ?? Data()
        guard data.count <= maximumBytes else { throw ModelCatalogError.invalidManifest }
        return data
    }
}
