import CoreMedia
import Foundation
import VideoToolbox

struct HardwareStatus: Equatable, Sendable {
    let hevcHardwareEncoderAvailable: Bool
    let h264HardwareEncoderAvailable: Bool

    var label: String {
        if hevcHardwareEncoderAvailable && h264HardwareEncoderAvailable { return "Media engines ready" }
        if hevcHardwareEncoderAvailable { return "HEVC engine ready" }
        if h264HardwareEncoderAvailable { return "H.264 engine ready" }
        return "Software fallback"
    }
}

enum HardwareProbe {
    static func current() -> HardwareStatus {
        HardwareStatus(
            hevcHardwareEncoderAvailable: canCreateHardwareEncoder(codec: kCMVideoCodecType_HEVC),
            h264HardwareEncoderAvailable: canCreateHardwareEncoder(codec: kCMVideoCodecType_H264)
        )
    }

    private static func canCreateHardwareEncoder(codec: CMVideoCodecType) -> Bool {
        let specification: CFDictionary = [
            kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder: true
        ] as CFDictionary
        var session: VTCompressionSession?
        let status = VTCompressionSessionCreate(
            allocator: nil,
            width: 320,
            height: 240,
            codecType: codec,
            encoderSpecification: specification,
            imageBufferAttributes: nil,
            compressedDataAllocator: nil,
            outputCallback: nil,
            refcon: nil,
            compressionSessionOut: &session
        )
        guard status == noErr, let session else { return false }
        defer { VTCompressionSessionInvalidate(session) }

        // Creation requested hardware explicitly, so a successful session is a
        // stronger and safer preflight signal than allowing a software fallback.
        return true
    }
}
