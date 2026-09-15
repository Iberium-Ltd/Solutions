@preconcurrency import AVFoundation
import CoreMedia
import CoreVideo
import Darwin
import Foundation

/// A dependency-free end-to-end gate for the AVFoundation pipeline. It is kept
/// outside the app target because this Mac has Command Line Tools, not XCTest.
@main
struct AlchemistSmoke {
    static func main() async {
        do {
            let root = FileManager.default.temporaryDirectory
                .appendingPathComponent("AlchemistSmoke-\(UUID().uuidString)", isDirectory: true)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            defer { try? FileManager.default.removeItem(at: root) }

            let source = root.appendingPathComponent("fixture.mp4")
            try verifySafeSameFolderPlan(source: source, folder: root)
            // Keep an AAC track in the source fixture. The production encoder
            // drains video and audio independently, so a video-only fixture
            // cannot catch regressions where audio falls behind at the end.
            try await makeFixture(at: source, width: 960, height: 540, frames: 90)
            let input = try await MediaProbe.inspect(source)
            guard input.width == 960, input.height == 540, input.codec == "H.264" else {
                throw SmokeError.assertion("Fixture metadata was not the expected 960 × 540 H.264 video")
            }
            let sourceAsset = AVURLAsset(url: source)
            guard try await sourceAsset.loadTracks(withMediaType: .audio).isEmpty == false else {
                throw SmokeError.assertion("Fixture did not contain its expected AAC audio track")
            }
            let originalBytes = input.sizeBytes

            var item = VideoItem(url: source)
            item.metadata = input
            var recipe = CompressionRecipe()
            recipe.preset = .custom
            recipe.codec = .hevc
            recipe.quality = 0.35
            recipe.resolution = .p480
            recipe.container = .mp4

            var chosenFolder = ExportOptions()
            chosenFolder.mode = .chosenFolder
            chosenFolder.folderURL = root
            chosenFolder.keepOriginalName = false

            let firstUpdates = UpdateCapture()
            let firstResult = try await TranscodeEngine().transcode(
                item: item,
                recipe: recipe,
                export: chosenFolder,
                update: { firstUpdates.record($0) }
            )
            let firstOutput = try await MediaProbe.inspect(firstResult.outputURL)
            guard FileManager.default.fileExists(atPath: firstResult.outputURL.path), firstResult.outputBytes > 0 else {
                throw SmokeError.assertion("Chosen-folder output was not written")
            }
            guard firstOutput.width == 852, firstOutput.height == 480, firstOutput.codec == "HEVC", firstOutput.duration > 0.9 else {
                throw SmokeError.assertion("HEVC resize result was not playable 852 × 480 video")
            }
            let firstOutputAsset = AVURLAsset(url: firstResult.outputURL)
            guard try await firstOutputAsset.loadTracks(withMediaType: .audio).isEmpty == false else {
                throw SmokeError.assertion("Audio-bearing source lost its audio track during HEVC export")
            }
            let updates = firstUpdates.snapshot()
            guard updates.contains(where: { $0.phase == .encoding }),
                  updates.last?.progress == 1,
                  updates.last?.phase == .committing else {
                throw SmokeError.assertion("Transcode progress did not report an encoding phase and a completed commit")
            }
            guard (try await MediaProbe.inspect(source)).sizeBytes == originalBytes else {
                throw SmokeError.assertion("Chosen-folder export altered its source")
            }

            // Regression for the former 99% / unresponsive-stop path. The
            // cancellation is issued exactly as the writer enters its final
            // flush, before it can move or replace any source file.
            let cancellationEngine = TranscodeEngine()
            let finalizationCanceller = FinalizationCanceller(engine: cancellationEngine)
            var didCancel = false
            do {
                _ = try await cancellationEngine.transcode(
                    item: item,
                    recipe: recipe,
                    export: chosenFolder,
                    update: { finalizationCanceller.observe($0) }
                )
            } catch let error as AlchemistError {
                if case .cancelled = error { didCancel = true }
            }
            guard didCancel, finalizationCanceller.didFire else {
                throw SmokeError.assertion("Cancelling during writer finalization did not return promptly")
            }
            guard (try await MediaProbe.inspect(source)).sizeBytes == originalBytes else {
                throw SmokeError.assertion("Finalization cancellation altered its source")
            }

            var replaceOriginal = ExportOptions()
            replaceOriginal.mode = .sameFolder
            replaceOriginal.replaceOriginal = true
            let replacement = try await TranscodeEngine().transcode(
                item: item,
                recipe: recipe,
                export: replaceOriginal,
                update: { _ in }
            )
            let replacedOutput = try await MediaProbe.inspect(replacement.outputURL)
            guard replacement.outputURL == source, replacedOutput.codec == "HEVC" else {
                throw SmokeError.assertion("Atomic source replacement did not finish with HEVC at the source URL")
            }
            let remainingFiles = try FileManager.default.contentsOfDirectory(atPath: root.path)
            guard !remainingFiles.contains(where: { $0.hasPrefix(".fixture.alchemist-") }) else {
                throw SmokeError.assertion("Replacement left a staging file behind")
            }

            print("SMOKE PASS: AAC preservation, progress completion, responsive finalization cancellation, source safety, and atomic replacement")
        } catch {
            fputs("SMOKE FAIL: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
    }

    private static func verifySafeSameFolderPlan(source: URL, folder: URL) throws {
        try Data("original".utf8).write(to: source)
        defer { try? FileManager.default.removeItem(at: source) }
        var export = ExportOptions()
        export.mode = .chosenFolder
        export.folderURL = folder
        export.keepOriginalName = true
        export.collisionPolicy = .overwrite
        let plan = try OutputPlanner.plan(for: source, options: export, recipe: CompressionRecipe())
        guard FileManager.default.fileExists(atPath: source.path),
              plan.finalURL.standardizedFileURL != source.standardizedFileURL,
              plan.stagingURL.standardizedFileURL != source.standardizedFileURL else {
            throw SmokeError.assertion("Safe same-folder overwrite planning would touch the source before encoding")
        }
    }

    private static func makeFixture(at url: URL, width: Int, height: Int, frames: Int) async throws {
        let videoURL = url.deletingLastPathComponent().appendingPathComponent("fixture-video.mp4")
        let audioURL = url.deletingLastPathComponent().appendingPathComponent("fixture-tone.m4a")
        defer {
            try? FileManager.default.removeItem(at: videoURL)
            try? FileManager.default.removeItem(at: audioURL)
        }

        try await makeVideoFixture(at: videoURL, width: width, height: height, frames: frames)
        try makeTone(at: audioURL, duration: Double(frames) / 30)
        try await mux(video: videoURL, audio: audioURL, into: url)
    }

    private static func makeVideoFixture(at url: URL, width: Int, height: Int, frames: Int) async throws {
        let writer = try AVAssetWriter(outputURL: url, fileType: .mp4)
        let settings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                AVVideoAverageBitRateKey: 1_600_000,
                AVVideoExpectedSourceFrameRateKey: 30
            ]
        ]
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height
            ]
        )
        guard writer.canAdd(input) else { throw SmokeError.assertion("Cannot prepare fixture writer") }
        writer.add(input)
        guard writer.startWriting() else { throw writer.error ?? SmokeError.assertion("Cannot start fixture writer") }
        writer.startSession(atSourceTime: .zero)

        for frame in 0..<frames {
            while !input.isReadyForMoreMediaData {
                try await Task.sleep(nanoseconds: 2_000_000)
            }
            guard let pool = adaptor.pixelBufferPool else { throw SmokeError.assertion("Fixture pixel-buffer pool unavailable") }
            var buffer: CVPixelBuffer?
            guard CVPixelBufferPoolCreatePixelBuffer(nil, pool, &buffer) == kCVReturnSuccess, let buffer else {
                throw SmokeError.assertion("Could not allocate a fixture frame")
            }
            CVPixelBufferLockBaseAddress(buffer, [])
            if let bytes = CVPixelBufferGetBaseAddress(buffer) {
                memset(bytes, Int32((frame * 11) % 255), CVPixelBufferGetDataSize(buffer))
            }
            CVPixelBufferUnlockBaseAddress(buffer, [])
            guard adaptor.append(buffer, withPresentationTime: CMTime(value: Int64(frame), timescale: 30)) else {
                throw writer.error ?? SmokeError.assertion("Could not append a fixture frame")
            }
        }

        input.markAsFinished()
        try await withCheckedThrowingContinuation { continuation in
            writer.finishWriting {
                if writer.status == .completed {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: writer.error ?? SmokeError.assertion("Fixture writer failed"))
                }
            }
        }
    }

    private static func makeTone(at url: URL, duration: Double) throws {
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVSampleRateKey: 48_000,
            AVNumberOfChannelsKey: 2,
            AVEncoderBitRateKey: 128_000
        ]
        let file = try AVAudioFile(
            forWriting: url,
            settings: settings,
            commonFormat: .pcmFormatFloat32,
            interleaved: false
        )
        let sampleRate = file.processingFormat.sampleRate
        let frameCapacity: AVAudioFrameCount = 1_024
        var remaining = max(1, Int((duration * sampleRate).rounded()))
        var sampleIndex = 0

        while remaining > 0 {
            let count = min(Int(frameCapacity), remaining)
            guard let buffer = AVAudioPCMBuffer(
                pcmFormat: file.processingFormat,
                frameCapacity: frameCapacity
            ), let channels = buffer.floatChannelData else {
                throw SmokeError.assertion("Could not allocate an AAC fixture buffer")
            }
            buffer.frameLength = AVAudioFrameCount(count)
            for channel in 0..<Int(file.processingFormat.channelCount) {
                for frame in 0..<count {
                    let phase = (Double(sampleIndex + frame) * 2 * .pi * 440) / sampleRate
                    channels[channel][frame] = Float(sin(phase) * 0.12)
                }
            }
            try file.write(from: buffer)
            sampleIndex += count
            remaining -= count
        }
    }

    private static func mux(video videoURL: URL, audio audioURL: URL, into outputURL: URL) async throws {
        let videoAsset = AVURLAsset(url: videoURL)
        let audioAsset = AVURLAsset(url: audioURL)
        guard let videoTrack = try await videoAsset.loadTracks(withMediaType: .video).first,
              let audioTrack = try await audioAsset.loadTracks(withMediaType: .audio).first else {
            throw SmokeError.assertion("Fixture tracks could not be loaded for muxing")
        }
        let videoDuration = try await videoAsset.load(.duration)
        let audioDuration = try await audioAsset.load(.duration)
        let composition = AVMutableComposition()
        guard let compositionVideo = composition.addMutableTrack(
            withMediaType: .video,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ), let compositionAudio = composition.addMutableTrack(
            withMediaType: .audio,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ) else {
            throw SmokeError.assertion("Could not create fixture composition tracks")
        }
        try compositionVideo.insertTimeRange(
            CMTimeRange(start: .zero, duration: videoDuration),
            of: videoTrack,
            at: .zero
        )
        try compositionAudio.insertTimeRange(
            CMTimeRange(start: .zero, duration: CMTimeMinimum(videoDuration, audioDuration)),
            of: audioTrack,
            at: .zero
        )
        guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetPassthrough) else {
            throw SmokeError.assertion("Could not create fixture mux exporter")
        }
        exporter.shouldOptimizeForNetworkUse = true
        if #available(macOS 15.0, *) {
            try await exporter.export(to: outputURL, as: .mp4)
        } else {
            exporter.outputURL = outputURL
            exporter.outputFileType = .mp4
            try await legacyExport(exporter)
        }
    }

    @available(macOS, introduced: 10.7, deprecated: 15.0)
    private static func legacyExport(_ exporter: AVAssetExportSession) async throws {
        let session = ExportSessionBox(exporter)
        try await withCheckedThrowingContinuation { continuation in
            session.value.exportAsynchronously {
                if session.value.status == .completed {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: session.value.error ?? SmokeError.assertion("Fixture mux exporter failed"))
                }
            }
        }
    }
}

private final class UpdateCapture: @unchecked Sendable {
    private let lock = NSLock()
    private var updates: [TranscodeUpdate] = []

    func record(_ update: TranscodeUpdate) {
        lock.lock()
        updates.append(update)
        lock.unlock()
    }

    func snapshot() -> [TranscodeUpdate] {
        lock.lock()
        defer { lock.unlock() }
        return updates
    }
}

private final class FinalizationCanceller: @unchecked Sendable {
    private let lock = NSLock()
    private let engine: TranscodeEngine
    private var fired = false

    init(engine: TranscodeEngine) {
        self.engine = engine
    }

    var didFire: Bool {
        lock.lock()
        defer { lock.unlock() }
        return fired
    }

    func observe(_ update: TranscodeUpdate) {
        guard update.phase == .finalizing else { return }
        lock.lock()
        guard !fired else { lock.unlock(); return }
        fired = true
        lock.unlock()
        engine.cancelAll()
    }
}

private final class ExportSessionBox: @unchecked Sendable {
    let value: AVAssetExportSession

    init(_ value: AVAssetExportSession) {
        self.value = value
    }
}

private enum SmokeError: LocalizedError {
    case assertion(String)

    var errorDescription: String? {
        switch self {
        case .assertion(let message): message
        }
    }
}
