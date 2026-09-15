import AppKit
import AVFoundation
import CoreGraphics
import Foundation

enum VideoCodec: String, CaseIterable, Identifiable, Codable {
    case hevc
    case h264

    var id: String { rawValue }

    var title: String {
        switch self {
        case .hevc: "HEVC (H.265)"
        case .h264: "H.264"
        }
    }

    var shortTitle: String {
        switch self {
        case .hevc: "HEVC"
        case .h264: "H.264"
        }
    }

    var avCodec: AVVideoCodecType {
        switch self {
        case .hevc: .hevc
        case .h264: .h264
        }
    }
}

enum CompressionPreset: String, CaseIterable, Identifiable, Codable {
    case smart
    case nearOriginal
    case balanced
    case smallest
    case sharing
    case custom

    var id: String { rawValue }

    var title: String {
        switch self {
        case .smart: "Smart"
        case .nearOriginal: "Near-original"
        case .balanced: "Balanced"
        case .smallest: "Smallest file"
        case .sharing: "Share anywhere"
        case .custom: "Custom"
        }
    }

    var detail: String {
        switch self {
        case .smart: "Best space / quality balance"
        case .nearOriginal: "Keep visual detail"
        case .balanced: "Smaller, still crisp"
        case .smallest: "Push compression hard"
        case .sharing: "Fast upload and playback"
        case .custom: "Your exact settings"
        }
    }

    var defaultQuality: Double {
        switch self {
        case .nearOriginal: 0.86
        case .smart: 0.70
        case .balanced: 0.58
        case .sharing: 0.46
        case .smallest: 0.30
        case .custom: 0.60
        }
    }

    var defaultResolution: ResolutionOption {
        switch self {
        case .nearOriginal, .smart: .source
        case .balanced: .p1080
        case .sharing: .p1080
        case .smallest: .p720
        case .custom: .source
        }
    }
}

enum ResolutionOption: String, CaseIterable, Identifiable, Codable {
    case source
    case p2160
    case p1440
    case p1080
    case p720
    case p480

    var id: String { rawValue }

    var title: String {
        switch self {
        case .source: "Keep original"
        case .p2160: "4K · 2160p"
        case .p1440: "1440p"
        case .p1080: "1080p"
        case .p720: "720p"
        case .p480: "480p"
        }
    }

    var targetHeight: Int? {
        switch self {
        case .source: nil
        case .p2160: 2160
        case .p1440: 1440
        case .p1080: 1080
        case .p720: 720
        case .p480: 480
        }
    }
}

enum ContainerFormat: String, CaseIterable, Identifiable, Codable {
    case automatic
    case mp4
    case mov

    var id: String { rawValue }

    var title: String {
        switch self {
        case .automatic: "Automatic"
        case .mp4: "MP4"
        case .mov: "MOV"
        }
    }

    func fileType(for source: URL) -> AVFileType {
        switch self {
        case .mov: return AVFileType.mov
        case .mp4: return AVFileType.mp4
        case .automatic:
            return source.pathExtension.lowercased() == "mov" ? AVFileType.mov : AVFileType.mp4
        }
    }

    func fileExtension(for source: URL) -> String {
        switch fileType(for: source) {
        case .mov: "mov"
        default: "mp4"
        }
    }
}

enum DestinationMode: String, CaseIterable, Identifiable, Codable {
    case sameFolder
    case chosenFolder

    var id: String { rawValue }

    var title: String {
        switch self {
        case .sameFolder: "Same folder"
        case .chosenFolder: "Choose folder"
        }
    }
}

enum CollisionPolicy: String, CaseIterable, Identifiable, Codable {
    case increment
    case overwrite

    var id: String { rawValue }

    var title: String {
        switch self {
        case .increment: "Keep both"
        case .overwrite: "Overwrite existing"
        }
    }
}

enum PerformanceMode: String, CaseIterable, Identifiable, Codable {
    case efficient
    case balanced
    case turbo
    case max

    var id: String { rawValue }

    var title: String {
        switch self {
        case .efficient: "Quiet"
        case .balanced: "Balanced"
        case .turbo: "Turbo"
        case .max: "M4 Max"
        }
    }

    /// More parallel encodes keep the hardware media engines and CPU pipeline fed.
    /// Values are deliberately capped so memory pressure does not reduce throughput.
    var recommendedParallelism: Int {
        switch self {
        case .efficient: 1
        case .balanced: 1
        case .turbo: 2
        case .max: 4
        }
    }

    var detail: String {
        switch self {
        case .efficient: "One lane · lowest contention"
        case .balanced: "One lane · best while multitasking"
        case .turbo: "Two lanes · matches M4 Max encode engines"
        case .max: "Four lanes · maximum pressure"
        }
    }
}

struct CompressionRecipe: Equatable, Codable {
    var preset: CompressionPreset = .smart
    var codec: VideoCodec = .hevc
    /// 0 means smallest, 1 means near-original.
    var quality: Double = CompressionPreset.smart.defaultQuality
    var resolution: ResolutionOption = CompressionPreset.smart.defaultResolution
    var container: ContainerFormat = .automatic
    var audioBitrateKbps: Int = 160
    var keyframeSeconds: Int = 4
    /// Overrides the adaptive bitrate when non-nil. Kept intentionally advanced.
    var targetBitrateMbps: Double? = nil

    mutating func apply(_ newPreset: CompressionPreset) {
        preset = newPreset
        guard newPreset != .custom else { return }
        quality = newPreset.defaultQuality
        resolution = newPreset.defaultResolution
        codec = .hevc
        targetBitrateMbps = nil
    }

    var qualityLabel: String {
        switch quality {
        case 0..<0.28: "Aggressive"
        case 0..<0.48: "Compact"
        case 0..<0.68: "Balanced"
        case 0..<0.84: "High"
        default: "Near-original"
        }
    }
}

struct ExportOptions: Equatable, Codable {
    var mode: DestinationMode = .chosenFolder
    var folderURL: URL? = nil
    /// Retained for compatibility with early local builds. Chosen-folder
    /// exports now always retain the source name.
    var keepOriginalName: Bool = true
    // Only applies to Same folder. The UI enables this automatically when that
    // destination is selected; chosen-folder exports never replace a source.
    var replaceOriginal: Bool = false
    /// Re-running a job replaces the previous output instead of producing
    /// filename copies such as "Movie 2.mp4".
    var collisionPolicy: CollisionPolicy = .overwrite

    func folder(for source: URL) -> URL {
        switch mode {
        case .sameFolder:
            source.deletingLastPathComponent()
        case .chosenFolder:
            folderURL ?? source.deletingLastPathComponent()
        }
    }
}

struct VideoMetadata: Equatable, Hashable {
    let width: Int
    let height: Int
    let duration: Double
    let frameRate: Double
    let codec: String
    let isHDR: Bool
    let sizeBytes: Int64

    var resolutionText: String { "\(width) × \(height)" }
    var verticalResolution: Int { min(width, height) }
    var durationText: String { DurationFormatter.string(for: duration) }
    var sizeText: String { ByteCountFormatter.alchemistString(sizeBytes) }
    var fpsText: String { frameRate > 0 ? String(format: "%.0f fps", frameRate) : "—" }
}

enum JobState: Equatable {
    case analyzing
    case ready
    case encoding
    case complete
    case failed(String)
    case cancelled

    var label: String {
        switch self {
        case .analyzing: "Reading"
        case .ready: "Ready"
        case .encoding: "Compressing"
        case .complete: "Done"
        case .failed: "Needs attention"
        case .cancelled: "Cancelled"
        }
    }
}

enum EncodingPhase: String, Equatable, Sendable {
    case preparing
    case encoding
    case finishingAudio
    case finalizing
    case committing
    case cancelling

    var label: String {
        switch self {
        case .preparing: "Preparing engine"
        case .encoding: "Compressing"
        case .finishingAudio: "Finishing audio"
        case .finalizing: "Finalizing file"
        case .committing: "Saving output"
        case .cancelling: "Stopping safely"
        }
    }

    var systemImage: String {
        switch self {
        case .preparing: "gearshape.2"
        case .encoding: "bolt.fill"
        case .finishingAudio: "waveform"
        case .finalizing: "seal"
        case .committing: "externaldrive.badge.checkmark"
        case .cancelling: "xmark.circle"
        }
    }
}

struct TranscodeUpdate: Sendable {
    let progress: Double
    let phase: EncodingPhase
    let processedMediaSeconds: Double
    let totalMediaSeconds: Double
}

struct VideoItem: Identifiable, Equatable {
    let id: UUID
    let url: URL
    var metadata: VideoMetadata?
    var isSelected: Bool
    var state: JobState
    var phase: EncodingPhase?
    var progress: Double
    var outputURL: URL?
    var outputBytes: Int64?
    var startedAt: Date?

    init(url: URL) {
        id = UUID()
        self.url = url
        metadata = nil
        isSelected = true
        state = .analyzing
        phase = nil
        progress = 0
        outputURL = nil
        outputBytes = nil
        startedAt = nil
    }

    var displayName: String { url.deletingPathExtension().lastPathComponent }
    var fileName: String { url.lastPathComponent }
    var savingsFraction: Double? {
        guard let original = metadata?.sizeBytes, let outputBytes, original > 0 else { return nil }
        return max(0, 1 - (Double(outputBytes) / Double(original)))
    }
}

struct OutputPlan {
    let stagingURL: URL
    let finalURL: URL
    let replaceSource: Bool
    let collisionPolicy: CollisionPolicy
    let fileType: AVFileType
}

struct TranscodeResult {
    let outputURL: URL
    let outputBytes: Int64
}

enum AlchemistError: LocalizedError {
    case noVideoTrack(URL)
    case unableToCreateOutput(URL)
    case sourceCannotBeReplaced(URL)
    case hdrUnsupported(URL)
    case readerFailed(String)
    case writerFailed(String)
    case cancelled

    var errorDescription: String? {
        switch self {
        case .noVideoTrack(let url): "No video track was found in \(url.lastPathComponent)."
        case .unableToCreateOutput(let url): "Could not create \(url.lastPathComponent)."
        case .sourceCannotBeReplaced(let url): "\(url.lastPathComponent) cannot be replaced with the selected container."
        case .hdrUnsupported(let url): "\(url.lastPathComponent) is HDR. This SDR compressor deliberately stops before it can wash out HDR color; export an SDR version first."
        case .readerFailed(let message): message
        case .writerFailed(let message): message
        case .cancelled: "Cancelled"
        }
    }
}

enum DurationFormatter {
    static func string(for seconds: Double) -> String {
        guard seconds.isFinite else { return "—" }
        let value = max(0, Int(seconds.rounded()))
        let hours = value / 3_600
        let minutes = (value % 3_600) / 60
        let remaining = value % 60
        if hours > 0 { return String(format: "%d:%02d:%02d", hours, minutes, remaining) }
        return String(format: "%d:%02d", minutes, remaining)
    }

    static func etaString(for seconds: TimeInterval?) -> String {
        guard let seconds, seconds.isFinite, seconds >= 0 else { return "Calculating…" }
        if seconds < 60 { return "< 1 min" }
        return string(for: seconds)
    }
}

extension ByteCountFormatter {
    static func alchemistString(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        formatter.allowedUnits = [.useKB, .useMB, .useGB]
        formatter.includesUnit = true
        formatter.isAdaptive = true
        return formatter.string(fromByteCount: bytes)
    }
}

extension Int {
    var even: Int {
        let rounded = Swift.max(2, self)
        return rounded.isMultiple(of: 2) ? rounded : rounded - 1
    }
}
