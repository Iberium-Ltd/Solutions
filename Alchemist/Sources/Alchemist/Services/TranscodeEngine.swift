@preconcurrency import AVFoundation
import CoreMedia
import CoreVideo
import Foundation
import VideoToolbox
import AudioToolbox

/// A single-file reader / writer pipeline. AVAssetWriter hands HEVC and H.264 work
/// to Apple's hardware encoder on Apple Silicon when a supported encoder exists.
final class TranscodeEngine: @unchecked Sendable {
    private let activeControlsLock = NSLock()
    private var activeControls: [UUID: EncodingControl] = [:]

    /// Cancels the AVFoundation reader/writer objects directly. This is separate
    /// from Swift task cancellation so the UI can stop an active encode promptly.
    func cancelAll() {
        activeControlsLock.lock()
        let controls = Array(activeControls.values)
        activeControlsLock.unlock()
        controls.forEach { $0.cancel() }
    }

    func transcode(
        item: VideoItem,
        recipe: CompressionRecipe,
        export: ExportOptions,
        update: @escaping @Sendable (TranscodeUpdate) -> Void
    ) async throws -> TranscodeResult {
        try Task.checkCancellation()
        if item.metadata?.isHDR == true { throw AlchemistError.hdrUnsupported(item.url) }
        let plan = try OutputPlanner.plan(for: item.url, options: export, recipe: recipe)
        let control = EncodingControl()
        register(control, for: item.id)
        defer { unregister(control, for: item.id) }

        do {
            let result = try await withTaskCancellationHandler(operation: {
                try await self.perform(
                    source: item.url,
                    metadata: item.metadata,
                    recipe: recipe,
                    plan: plan,
                    control: control,
                    update: update
                )
            }, onCancel: {
                control.cancel()
            })
            return result
        } catch {
            OutputPlanner.discardStagingFile(for: plan)
            throw error
        }
    }

    private func register(_ control: EncodingControl, for id: UUID) {
        activeControlsLock.lock()
        activeControls[id] = control
        activeControlsLock.unlock()
    }

    private func unregister(_ control: EncodingControl, for id: UUID) {
        activeControlsLock.lock()
        if activeControls[id] === control { activeControls[id] = nil }
        activeControlsLock.unlock()
    }

    private func perform(
        source: URL,
        metadata: VideoMetadata?,
        recipe: CompressionRecipe,
        plan: OutputPlan,
        control: EncodingControl,
        update: @escaping @Sendable (TranscodeUpdate) -> Void
    ) async throws -> TranscodeResult {
        if control.isCancelled { throw AlchemistError.cancelled }

        let asset = AVURLAsset(url: source)
        let videoTracks = try await asset.loadTracks(withMediaType: .video)
        guard let videoTrack = videoTracks.first else { throw AlchemistError.noVideoTrack(source) }
        let audioTrack = try await asset.loadTracks(withMediaType: .audio).first

        async let naturalSize = videoTrack.load(.naturalSize)
        async let preferredTransform = videoTrack.load(.preferredTransform)
        async let nominalFrameRate = videoTrack.load(.nominalFrameRate)
        async let estimatedDataRate = videoTrack.load(.estimatedDataRate)
        async let minimumFrameDuration = videoTrack.load(.minFrameDuration)
        async let formatDescriptions = videoTrack.load(.formatDescriptions)
        async let duration = asset.load(.duration)
        let (sourceSize, sourceTransform, sourceFPS, sourceDataRate, sourceMinFrameDuration, formats, assetDuration) = try await (
            naturalSize, preferredTransform, nominalFrameRate, estimatedDataRate, minimumFrameDuration, formatDescriptions, duration
        )
        if formats.contains(where: MediaProbe.isHDRFormat) { throw AlchemistError.hdrUnsupported(source) }
        let durationSeconds = max(0.001, CMTimeGetSeconds(assetDuration))
        let renderPlan = RenderPlan(
            naturalSize: sourceSize,
            preferredTransform: sourceTransform,
            requestedResolution: recipe.resolution,
            sourceFrameRate: Double(sourceFPS),
            sourceMinFrameDuration: sourceMinFrameDuration
        )
        let bitrate = resolvedBitrate(
            recipe: recipe,
            dimensions: renderPlan.outputSize,
            frameRate: renderPlan.frameRate,
            sourceDataRate: Double(sourceDataRate)
        )

        let reader = try AVAssetReader(asset: asset)
        let writer = try AVAssetWriter(outputURL: plan.stagingURL, fileType: plan.fileType)
        control.attach(reader: reader, writer: writer)
        writer.shouldOptimizeForNetworkUse = plan.fileType == .mp4

        let videoOutput = AVAssetReaderVideoCompositionOutput(
            videoTracks: [videoTrack],
            videoSettings: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange
            ]
        )
        videoOutput.alwaysCopiesSampleData = false
        videoOutput.videoComposition = renderPlan.videoComposition(for: videoTrack, duration: assetDuration)

        let videoSettings = makeVideoSettings(
            codec: recipe.codec,
            size: renderPlan.outputSize,
            frameRate: renderPlan.frameRate,
            bitrate: bitrate,
            keyframeSeconds: recipe.keyframeSeconds
        )
        guard writer.canApply(outputSettings: videoSettings, forMediaType: .video) else {
            throw AlchemistError.writerFailed("The selected \(recipe.codec.title) settings are not available on this Mac.")
        }
        let videoInput = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
        videoInput.expectsMediaDataInRealTime = false

        guard reader.canAdd(videoOutput), writer.canAdd(videoInput) else {
            throw AlchemistError.writerFailed("Alchemist could not prepare the video pipeline.")
        }
        reader.add(videoOutput)
        writer.add(videoInput)

        var audioPair: MediaPair?
        if let audioTrack {
            audioPair = try await makeAudioPair(
                track: audioTrack,
                recipe: recipe,
                reader: reader,
                writer: writer
            )
        }

        let reporter = TranscodeProgressReporter(
            duration: durationSeconds,
            hasAudio: audioPair != nil,
            callback: update
        )
        reporter.transition(to: .preparing)

        guard reader.startReading() else {
            throw AlchemistError.readerFailed(reader.error?.localizedDescription ?? "Unable to read the source video.")
        }
        guard writer.startWriting() else {
            throw AlchemistError.writerFailed(writer.error?.localizedDescription ?? "Unable to start the hardware encoder.")
        }
        writer.startSession(atSourceTime: .zero)

        let videoPair = MediaPair(kind: .video, input: videoInput, output: videoOutput)
        reporter.transition(to: .encoding)
        try await drain(
            pairs: [videoPair] + (audioPair.map { [$0] } ?? []),
            reader: reader,
            writer: writer,
            control: control,
            reporter: reporter
        )

        if control.isCancelled || reader.status == .cancelled || writer.status == .cancelled {
            throw AlchemistError.cancelled
        }
        guard reader.status == .completed else {
            throw AlchemistError.readerFailed(reader.error?.localizedDescription ?? "The video reader stopped before completion.")
        }

        reporter.transition(to: .finalizing)
        try await finish(writer, control: control)
        if control.isCancelled { throw AlchemistError.cancelled }
        guard writer.status == .completed else {
            throw AlchemistError.writerFailed(writer.error?.localizedDescription ?? "The encoder stopped before completion.")
        }

        // From this point the media file is valid. A cancellation that arrives
        // after committing starts cannot truthfully be called a cancellation,
        // because the atomic move / replacement may already have happened.
        if control.isCancelled { throw AlchemistError.cancelled }
        reporter.transition(to: .committing)
        let finalURL = try OutputPlanner.finalize(plan)
        let values = try? finalURL.resourceValues(forKeys: [.fileSizeKey])
        let outputBytes = Int64(values?.fileSize ?? 0)
        reporter.complete()
        return TranscodeResult(outputURL: finalURL, outputBytes: outputBytes)
    }

    /// AAC needs no quality-lossy second encode, so preserve it whenever the
    /// source and selected container support it. Other formats use the reliable
    /// AAC conversion path below.
    private func makeAudioPair(
        track: AVAssetTrack,
        recipe: CompressionRecipe,
        reader: AVAssetReader,
        writer: AVAssetWriter
    ) async throws -> MediaPair {
        let descriptions = try await track.load(.formatDescriptions)
        if let description = descriptions.first,
           CMFormatDescriptionGetMediaType(description) == kCMMediaType_Audio,
           CMFormatDescriptionGetMediaSubType(description) == kAudioFormatMPEG4AAC {
            let output = AVAssetReaderTrackOutput(track: track, outputSettings: nil)
            output.alwaysCopiesSampleData = false
            let input = AVAssetWriterInput(
                mediaType: .audio,
                outputSettings: nil,
                sourceFormatHint: description
            )
            input.expectsMediaDataInRealTime = false
            if reader.canAdd(output), writer.canAdd(input) {
                reader.add(output)
                writer.add(input)
                return MediaPair(kind: .audio, input: input, output: output)
            }
        }

        let output = AVAssetReaderTrackOutput(
            track: track,
            outputSettings: [
                AVFormatIDKey: kAudioFormatLinearPCM,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsNonInterleaved: false
            ]
        )
        output.alwaysCopiesSampleData = false
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatMPEG4AAC,
            AVEncoderBitRateKey: max(64_000, recipe.audioBitrateKbps * 1_000),
            AVSampleRateKey: 48_000,
            AVNumberOfChannelsKey: 2
        ]
        guard writer.canApply(outputSettings: settings, forMediaType: .audio) else {
            throw AlchemistError.writerFailed("AAC audio settings are not available on this Mac.")
        }
        let input = AVAssetWriterInput(mediaType: .audio, outputSettings: settings)
        input.expectsMediaDataInRealTime = false
        guard reader.canAdd(output), writer.canAdd(input) else {
            throw AlchemistError.writerFailed("Alchemist could not prepare the audio pipeline.")
        }
        reader.add(output)
        writer.add(input)
        return MediaPair(kind: .audio, input: input, output: output)
    }

    private func makeVideoSettings(
        codec: VideoCodec,
        size: CGSize,
        frameRate: Double,
        bitrate: Int,
        keyframeSeconds: Int
    ) -> [String: Any] {
        let roundedFPS = max(1, Int(frameRate.rounded()))
        let compression: [String: Any] = [
            AVVideoAverageBitRateKey: bitrate,
            AVVideoExpectedSourceFrameRateKey: roundedFPS,
            AVVideoMaxKeyFrameIntervalKey: max(1, roundedFPS * keyframeSeconds),
            AVVideoAllowFrameReorderingKey: true,
            kVTCompressionPropertyKey_PrioritizeEncodingSpeedOverQuality as String: false
        ]
        let settings: [String: Any] = [
            AVVideoCodecKey: codec.avCodec,
            AVVideoWidthKey: Int(size.width),
            AVVideoHeightKey: Int(size.height),
            AVVideoCompressionPropertiesKey: compression,
            // Alchemist is intentionally M4 Max-first: fail explicitly instead
            // of quietly falling back to a slow software encoder.
            AVVideoEncoderSpecificationKey: [
                kVTVideoEncoderSpecification_RequireHardwareAcceleratedVideoEncoder as String: true
            ]
        ]
        // On this macOS SDK AVAssetWriter rejects the advertised H.264 and HEVC
        // profile strings in `canApply`. Let the hardware encoder negotiate a
        // compatible profile from the codec and pixel format instead.
        return settings
    }

    private func resolvedBitrate(
        recipe: CompressionRecipe,
        dimensions: CGSize,
        frameRate: Double,
        sourceDataRate: Double
    ) -> Int {
        if let overridden = recipe.targetBitrateMbps, overridden > 0 {
            return max(200_000, Int(overridden * 1_000_000))
        }

        // Bits per pixel / frame is a stable, source-agnostic VBR target.
        // HEVC needs materially fewer bits than H.264 for equivalent quality.
        let minBPP: Double = recipe.codec == .hevc ? 0.026 : 0.050
        let maxBPP: Double = recipe.codec == .hevc ? 0.110 : 0.170
        let qualityBPP = minBPP + ((maxBPP - minBPP) * recipe.quality)
        let sourceCap = sourceDataRate > 0 ? Int(sourceDataRate * 1.08) : Int.max
        let calculated = Int(dimensions.width * dimensions.height * max(12, frameRate) * qualityBPP)
        return min(sourceCap, max(250_000, calculated))
    }

    private func drain(
        pairs: [MediaPair],
        reader: AVAssetReader,
        writer: AVAssetWriter,
        control: EncodingControl,
        reporter: TranscodeProgressReporter
    ) async throws {
        defer { control.clearCancellationHandler() }
        try await withCheckedThrowingContinuation { continuation in
            let coordinator = DrainCoordinator(remaining: pairs.count, continuation: continuation)
            control.setCancellationHandler {
                reader.cancelReading()
                writer.cancelWriting()
                coordinator.fail(AlchemistError.cancelled)
            }

            for pair in pairs {
                // Separate queues are important: an unbounded video feed must
                // never starve audio until the UI appears stuck at 99%.
                let queue = DispatchQueue(
                    label: "com.alchemist.encoder.\(UUID().uuidString).\(pair.kind.rawValue)",
                    qos: .userInitiated
                )
                pair.input.requestMediaDataWhenReady(on: queue) {
                    while pair.input.isReadyForMoreMediaData {
                        if control.isCancelled {
                            reader.cancelReading()
                            writer.cancelWriting()
                            coordinator.fail(AlchemistError.cancelled)
                            return
                        }

                        guard let sample = pair.output.copyNextSampleBuffer() else {
                            pair.input.markAsFinished()
                            reporter.markFinished(pair.kind)
                            coordinator.finishedOne(pair.kind)
                            return
                        }

                        guard pair.input.append(sample) else {
                            let error = writer.error?.localizedDescription ?? "Unable to append media to the output file."
                            reader.cancelReading()
                            writer.cancelWriting()
                            coordinator.fail(AlchemistError.writerFailed(error))
                            return
                        }

                        let timestamp = CMTimeGetSeconds(CMSampleBufferGetPresentationTimeStamp(sample))
                        reporter.reportSample(for: pair.kind, timestamp: timestamp)
                    }
                }
            }
        }
    }

    private func finish(_ writer: AVAssetWriter, control: EncodingControl) async throws {
        defer { control.clearCancellationHandler() }
        try await withCheckedThrowingContinuation { continuation in
            let coordinator = FinishCoordinator(continuation: continuation)
            control.setCancellationHandler {
                writer.cancelWriting()
                coordinator.fail(AlchemistError.cancelled)
            }
            guard !control.isCancelled else {
                coordinator.fail(AlchemistError.cancelled)
                return
            }
            writer.finishWriting {
                if writer.status == .completed {
                    coordinator.succeed()
                } else if control.isCancelled || writer.status == .cancelled {
                    coordinator.fail(AlchemistError.cancelled)
                } else {
                    coordinator.fail(AlchemistError.writerFailed(
                        writer.error?.localizedDescription ?? "Unable to finish the output file."
                    ))
                }
            }
        }
    }
}

private enum MediaKind: String, Hashable {
    case video
    case audio
}

private struct MediaPair {
    let kind: MediaKind
    let input: AVAssetWriterInput
    let output: AVAssetReaderOutput
}

private final class EncodingControl: @unchecked Sendable {
    private let lock = NSLock()
    private var reader: AVAssetReader?
    private var writer: AVAssetWriter?
    private var cancellationHandler: (() -> Void)?
    private var cancelled = false

    var isCancelled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return cancelled
    }

    func attach(reader: AVAssetReader, writer: AVAssetWriter) {
        lock.lock()
        self.reader = reader
        self.writer = writer
        let shouldCancel = cancelled
        lock.unlock()
        if shouldCancel {
            reader.cancelReading()
            writer.cancelWriting()
        }
    }

    func cancel() {
        lock.lock()
        cancelled = true
        let currentReader = reader
        let currentWriter = writer
        let handler = cancellationHandler
        lock.unlock()
        currentReader?.cancelReading()
        currentWriter?.cancelWriting()
        handler?()
    }

    func setCancellationHandler(_ handler: @escaping () -> Void) {
        lock.lock()
        cancellationHandler = handler
        let shouldCancel = cancelled
        lock.unlock()
        if shouldCancel { handler() }
    }

    func clearCancellationHandler() {
        lock.lock()
        cancellationHandler = nil
        lock.unlock()
    }
}

private final class DrainCoordinator: @unchecked Sendable {
    private let lock = NSLock()
    private var remaining: Int
    private var completed = false
    private var finishedKinds: Set<MediaKind> = []
    private let continuation: CheckedContinuation<Void, Error>

    init(remaining: Int, continuation: CheckedContinuation<Void, Error>) {
        self.remaining = remaining
        self.continuation = continuation
    }

    func finishedOne(_ kind: MediaKind) {
        lock.lock()
        guard !completed else { lock.unlock(); return }
        guard finishedKinds.insert(kind).inserted else { lock.unlock(); return }
        remaining -= 1
        let shouldFinish = remaining == 0
        if shouldFinish { completed = true }
        lock.unlock()
        if shouldFinish { continuation.resume() }
    }

    func fail(_ error: Error) {
        lock.lock()
        guard !completed else { lock.unlock(); return }
        completed = true
        lock.unlock()
        continuation.resume(throwing: error)
    }
}

/// Tracks both tracks' media time. Video and audio are processed concurrently,
/// so a weighted aggregate is meaningful for ETA without reporting a false 99%
/// while AAC or the container is still being written.
private final class TranscodeProgressReporter: @unchecked Sendable {
    private let lock = NSLock()
    private let duration: Double
    private let hasAudio: Bool
    private var lastReport = Date.distantPast
    private var videoFraction = 0.0
    private var audioFraction = 0.0
    private var videoFinished = false
    private var audioFinished = false
    private let callback: @Sendable (TranscodeUpdate) -> Void

    init(
        duration: Double,
        hasAudio: Bool,
        callback: @escaping @Sendable (TranscodeUpdate) -> Void
    ) {
        self.duration = max(0.001, duration)
        self.hasAudio = hasAudio
        self.callback = callback
    }

    func reportSample(for kind: MediaKind, timestamp: Double) {
        lock.lock()
        let fraction = min(1, max(0, timestamp / duration))
        switch kind {
        case .video: videoFraction = max(videoFraction, fraction)
        case .audio: audioFraction = max(audioFraction, fraction)
        }
        let phase = activePhase
        let now = Date()
        let shouldReport = now.timeIntervalSince(lastReport) >= 0.10
        if shouldReport { lastReport = now }
        let update = makeUpdate(phase: phase)
        lock.unlock()
        if shouldReport { callback(update) }
    }

    func markFinished(_ kind: MediaKind) {
        lock.lock()
        switch kind {
        case .video:
            videoFraction = 1
            videoFinished = true
        case .audio:
            audioFraction = 1
            audioFinished = true
        }
        lastReport = .now
        let update = makeUpdate(phase: activePhase)
        lock.unlock()
        callback(update)
    }

    func transition(to phase: EncodingPhase) {
        lock.lock()
        lastReport = .now
        let update = makeUpdate(phase: phase)
        lock.unlock()
        callback(update)
    }

    func complete() {
        lock.lock()
        videoFraction = 1
        audioFraction = 1
        videoFinished = true
        audioFinished = true
        lastReport = .now
        let update = makeUpdate(phase: .committing, progress: 1)
        lock.unlock()
        callback(update)
    }

    private var activePhase: EncodingPhase {
        if hasAudio, videoFinished, !audioFinished { return .finishingAudio }
        return .encoding
    }

    private func makeUpdate(phase: EncodingPhase, progress explicitProgress: Double? = nil) -> TranscodeUpdate {
        let weighted: Double
        if hasAudio {
            weighted = (videoFraction * 0.88) + (audioFraction * 0.12)
        } else {
            weighted = videoFraction
        }
        let progress = explicitProgress ?? min(1, max(0, weighted))
        return TranscodeUpdate(
            progress: progress,
            phase: phase,
            processedMediaSeconds: progress * duration,
            totalMediaSeconds: duration
        )
    }
}

private final class FinishCoordinator: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false
    private let continuation: CheckedContinuation<Void, Error>

    init(continuation: CheckedContinuation<Void, Error>) {
        self.continuation = continuation
    }

    func succeed() {
        lock.lock()
        guard !completed else { lock.unlock(); return }
        completed = true
        lock.unlock()
        continuation.resume()
    }

    func fail(_ error: Error) {
        lock.lock()
        guard !completed else { lock.unlock(); return }
        completed = true
        lock.unlock()
        continuation.resume(throwing: error)
    }
}

private struct RenderPlan {
    let outputSize: CGSize
    let preferredTransform: CGAffineTransform
    let sourceBounds: CGRect
    let frameRate: Double
    let sourceFrameDuration: CMTime

    init(
        naturalSize: CGSize,
        preferredTransform: CGAffineTransform,
        requestedResolution: ResolutionOption,
        sourceFrameRate: Double,
        sourceMinFrameDuration: CMTime
    ) {
        let transformedBounds = CGRect(origin: .zero, size: naturalSize).applying(preferredTransform)
        let displayWidth = max(2, Int(abs(transformedBounds.width).rounded()).even)
        let displayHeight = max(2, Int(abs(transformedBounds.height).rounded()).even)
        let sourceShortEdge = Double(min(displayWidth, displayHeight))
        let requestedShortEdge = Double(requestedResolution.targetHeight ?? Int(sourceShortEdge))
        let scale = min(1, requestedShortEdge / sourceShortEdge)
        outputSize = CGSize(
            width: Int((Double(displayWidth) * scale).rounded(.down)).even,
            height: Int((Double(displayHeight) * scale).rounded(.down)).even
        )
        self.preferredTransform = preferredTransform
        sourceBounds = transformedBounds
        frameRate = sourceFrameRate > 1 ? sourceFrameRate : 30
        sourceFrameDuration = sourceMinFrameDuration.isValid && sourceMinFrameDuration > .zero
            ? sourceMinFrameDuration
            : CMTime(value: 1, timescale: 600)
    }

    func videoComposition(for track: AVAssetTrack, duration: CMTime) -> AVVideoComposition {
        let composition = AVMutableVideoComposition()
        composition.renderSize = outputSize
        composition.frameDuration = sourceFrameDuration

        let instruction = AVMutableVideoCompositionInstruction()
        instruction.timeRange = CMTimeRange(start: .zero, duration: duration)
        let layer = AVMutableVideoCompositionLayerInstruction(assetTrack: track)
        let scale = outputSize.width / max(1, abs(sourceBounds.width))
        // Normalize any 90° / 180° track transform into the render rectangle,
        // then resize it. This avoids the classic portrait black-frame problem.
        let normalized = preferredTransform
            .concatenating(CGAffineTransform(translationX: -sourceBounds.minX, y: -sourceBounds.minY))
            .concatenating(CGAffineTransform(scaleX: scale, y: scale))
        layer.setTransform(normalized, at: .zero)
        instruction.layerInstructions = [layer]
        composition.instructions = [instruction]
        return composition
    }
}
