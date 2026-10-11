#if os(macOS)
import Foundation
import Darwin

struct HardwareEligibility {
    let supported: Bool
    let description: String
    static var current: HardwareEligibility {
        #if arch(arm64)
        guard ProcessInfo.processInfo.isOperatingSystemAtLeast(OperatingSystemVersion(majorVersion: 26, minorVersion: 4, patchVersion: 0)) else {
            return HardwareEligibility(supported: false, description: "Deepdesk’s embedded inference engine requires macOS 26.4 or later.")
        }
        var size = 0
        guard sysctlbyname("machdep.cpu.brand_string", nil, &size, nil, 0) == 0, size > 0 else {
            return HardwareEligibility(supported: false, description: "Deepdesk could not verify this Mac’s chip. Its embedded inference engine requires Apple M3 or newer.")
        }
        var buffer = [CChar](repeating: 0, count: size)
        guard sysctlbyname("machdep.cpu.brand_string", &buffer, &size, nil, 0) == 0 else {
            return HardwareEligibility(supported: false, description: "This Mac’s chip could not be verified.")
        }
        let chip = String(decoding: buffer.prefix(while: { $0 != 0 }).map { UInt8(bitPattern: $0) }, as: UTF8.self)
        guard let range = chip.range(of: "Apple M"),
              let family = Int(chip[range.upperBound...].prefix(while: { $0.isNumber })), family >= 3 else {
            return HardwareEligibility(supported: false, description: "Deepdesk’s embedded inference engine requires Apple M3 or newer. This Mac reports \(chip).")
        }
        return HardwareEligibility(supported: true, description: chip)
        #else
        return HardwareEligibility(supported: false, description: "Deepdesk requires an Apple Silicon Mac with an M3 or newer chip.")
        #endif
    }
}
#endif
