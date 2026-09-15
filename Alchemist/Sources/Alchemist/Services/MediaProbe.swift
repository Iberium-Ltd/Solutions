import AVFoundation
import CoreMedia
import Foundation

enum MediaProbe {
    static let supportedExtensions: Set<String> = [
        "mp4", "m4v", "mov", "avi", "mkv", "webm", "mts", "m2ts", "3gp"
    ]

    static func looksLikeVideo(_ url: URL) -> Bool {
        supportedExtensions.contains(url.pathExtension.lowercased())
    }

    static func inspect(_ url: URL) async throws -> VideoMetadata {
        let asset = AVURLAsset(url: url)
        let tracks = try await asset.loadTracks(withMediaType: .video)
        guard let videoTrack = tracks.first else { throw AlchemistError.noVideoTrack(url) }

        async let naturalSize = videoTrack.load(.naturalSize)
        async let preferredTransform = videoTrack.load(.preferredTransform)
        async let nominalFrameRate = videoTrack.load(.nominalFrameRate)
        async let duration = asset.load(.duration)
        async let formatDescriptions = videoTrack.load(.formatDescriptions)

        let (size, transform, frameRate, assetDuration, formats) = try await (
            naturalSize, preferredTransform, nominalFrameRate, duration, formatDescriptions
        )
        let renderedSize = size.applying(transform)
        let width = Int(abs(renderedSize.width).rounded()).even
        let height = Int(abs(renderedSize.height).rounded()).even
        let codec = formats.first.map(codecName) ?? "Video"
        let isHDR = formats.contains(where: isHDRFormat)
        let resourceValues = try? url.resourceValues(forKeys: [.fileSizeKey])
        let bytes = Int64(resourceValues?.fileSize ?? 0)

        return VideoMetadata(
            width: width,
            height: height,
            duration: CMTimeGetSeconds(assetDuration),
            frameRate: Double(frameRate),
            codec: codec,
            isHDR: isHDR,
            sizeBytes: bytes
        )
    }

    static func isHDRFormat(_ description: CMFormatDescription) -> Bool {
        let transfer = CMFormatDescriptionGetExtension(
            description,
            extensionKey: kCMFormatDescriptionExtension_TransferFunction
        ) as? String
        return transfer == (kCMFormatDescriptionTransferFunction_ITU_R_2100_HLG as String)
            || transfer == (kCMFormatDescriptionTransferFunction_SMPTE_ST_2084_PQ as String)
    }

    private static func codecName(_ description: CMFormatDescription) -> String {
        let subType = CMFormatDescriptionGetMediaSubType(description)
        switch subType {
        case kCMVideoCodecType_HEVC: return "HEVC"
        case kCMVideoCodecType_H264: return "H.264"
        case kCMVideoCodecType_AppleProRes422,
             kCMVideoCodecType_AppleProRes422HQ,
             kCMVideoCodecType_AppleProRes422LT,
             kCMVideoCodecType_AppleProRes422Proxy,
             kCMVideoCodecType_AppleProRes4444:
            return "ProRes"
        default:
            let value = UInt32(subType)
            let characters = [
                Character(UnicodeScalar((value >> 24) & 0xff) ?? "?"),
                Character(UnicodeScalar((value >> 16) & 0xff) ?? "?"),
                Character(UnicodeScalar((value >> 8) & 0xff) ?? "?"),
                Character(UnicodeScalar(value & 0xff) ?? "?")
            ]
            return String(characters).trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }
}

enum FolderScanner {
    static func videos(in directory: URL, recursive: Bool) -> [URL] {
        let keys: Set<URLResourceKey> = [.isRegularFileKey, .isDirectoryKey, .isHiddenKey]
        guard let enumerator = FileManager.default.enumerator(
            at: directory,
            includingPropertiesForKeys: Array(keys),
            options: [.skipsHiddenFiles, .skipsPackageDescendants]
        ) else { return [] }

        var found: [URL] = []
        for case let url as URL in enumerator {
            guard let values = try? url.resourceValues(forKeys: keys) else { continue }
            if values.isDirectory == true, !recursive {
                enumerator.skipDescendants()
                continue
            }
            if values.isRegularFile == true, MediaProbe.looksLikeVideo(url) {
                found.append(url)
            }
        }
        return found.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    }
}
