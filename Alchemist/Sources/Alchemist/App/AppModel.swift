import AppKit
import Combine
import Foundation
import UniformTypeIdentifiers

@MainActor
final class AppModel: ObservableObject {
    @Published var items: [VideoItem] = []
    @Published var recipe = CompressionRecipe()
    @Published var export = ExportOptions()
    @Published var performance: PerformanceMode = .turbo
    @Published var selectedResolutionGroup = "All resolutions"
    @Published var isScanning = false
    @Published var isCompressing = false
    @Published var showReplaceConfirmation = false
    @Published var alertMessage: String?
    @Published var hardwareStatus = HardwareStatus(hevcHardwareEncoderAvailable: false, h264HardwareEncoderAvailable: false)
    @Published var recursiveScan = true
    @Published private(set) var batchIDs: Set<UUID> = []
    @Published private(set) var batchStartedAt: Date?
    @Published private(set) var batchMediaRate: Double?
    @Published private(set) var isCancelling = false
    @Published private(set) var telemetryTick = Date()

    private let encoder = TranscodeEngine()
    private var batchTask: Task<Void, Never>?
    private var telemetryTimer: Timer?
    private var lastRateSample: (date: Date, mediaSeconds: Double)?

    var visibleItems: [VideoItem] {
        guard selectedResolutionGroup != "All resolutions" else { return items }
        return items.filter { resolutionGroup(for: $0.metadata) == selectedResolutionGroup }
    }

    var resolutionGroups: [String] {
        let groups = Set(items.compactMap { item in
            item.metadata.map { resolutionGroup(for: $0) }
        })
        let ordered = ["4K", "1440p", "1080p", "720p", "480p", "Other"]
        return ["All resolutions"] + ordered.filter(groups.contains)
    }

    var selectedReadyCount: Int {
        items.filter { $0.isSelected && $0.state == .ready }.count
    }

    var selectedSourceBytes: Int64 {
        items.filter { $0.isSelected }.compactMap(\.metadata?.sizeBytes).reduce(0, +)
    }

    var batchProgress: Double {
        let batch = batchItems
        let total = batch.reduce(0.0) { $0 + mediaWeight(for: $1) }
        guard total > 0 else { return 0 }
        let completed = batch.reduce(0.0) { $0 + (mediaWeight(for: $1) * effectiveProgress(for: $1)) }
        return min(1, max(0, completed / total))
    }

    var activeLanes: Int {
        items.filter { $0.state == .encoding }.count
    }

    var batchCompletedCount: Int {
        batchItems.filter {
            switch $0.state {
            case .complete, .failed, .cancelled: true
            default: false
            }
        }.count
    }

    var batchPhase: EncodingPhase? {
        if isCancelling { return .cancelling }
        let phases = batchItems.compactMap(\.phase)
        for phase in [EncodingPhase.committing, .finalizing, .finishingAudio, .preparing, .encoding] where phases.contains(phase) {
            return phase
        }
        return nil
    }

    var batchElapsed: TimeInterval {
        _ = telemetryTick
        guard let batchStartedAt else { return 0 }
        return max(0, Date().timeIntervalSince(batchStartedAt))
    }

    var batchElapsedText: String {
        DurationFormatter.string(for: batchElapsed)
    }

    var batchETA: TimeInterval? {
        guard isCompressing,
              batchPhase == .encoding,
              let batchMediaRate,
              batchMediaRate > 0 else { return nil }
        let remaining = max(0, totalBatchMediaSeconds - processedBatchMediaSeconds)
        return remaining / batchMediaRate
    }

    var batchETAText: String? {
        guard let batchETA else { return nil }
        return "ETA ≈ \(DurationFormatter.etaString(for: batchETA))"
    }

    var batchSpeedText: String? {
        guard let batchMediaRate, batchMediaRate.isFinite, batchMediaRate > 0 else { return nil }
        return String(format: "%.1f× realtime", batchMediaRate)
    }

    var batchStatusText: String {
        switch batchPhase {
        case .cancelling: "Stopping active encoders…"
        case .preparing: "Preparing hardware encoder…"
        case .finishingAudio: "Finishing audio…"
        case .finalizing: "Finalizing output — drive speed matters here."
        case .committing: "Saving output safely…"
        case .encoding, .none: "Compressing"
        }
    }

    var completedSavingsBytes: Int64 {
        items.reduce(Int64(0)) { partial, item in
            guard let original = item.metadata?.sizeBytes, let output = item.outputBytes else { return partial }
            return partial + max(0, original - output)
        }
    }

    var completedCount: Int {
        items.filter { $0.state == .complete }.count
    }

    func loadHardwareStatus() {
        Task {
            let status = await Task.detached(priority: .utility) {
                HardwareProbe.current()
            }.value
            hardwareStatus = status
        }
    }

    func chooseFiles() {
        let panel = NSOpenPanel()
        panel.title = "Add videos"
        panel.message = "Choose one or more videos to compress."
        panel.prompt = "Add videos"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = true
        panel.allowedContentTypes = [.movie, .mpeg4Movie, .quickTimeMovie]
        if panel.runModal() == .OK {
            add(urls: panel.urls)
        }
    }

    func chooseFolderAndScan() {
        let panel = NSOpenPanel()
        panel.title = "Scan a folder for videos"
        panel.message = "Alchemist will find every compatible video in this folder."
        panel.prompt = "Scan folder"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let folder = panel.url {
            scan(folder: folder)
        }
    }

    func chooseExportFolder() {
        let panel = NSOpenPanel()
        panel.title = "Choose export folder"
        panel.message = "Compressed files keep their original base names here."
        panel.prompt = "Use this folder"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let folder = panel.url {
            export.mode = .chosenFolder
            export.folderURL = folder
            export.replaceOriginal = false
        }
    }

    func scan(folder: URL) {
        guard !isScanning else { return }
        isScanning = true
        let recurse = recursiveScan
        Task { [weak self] in
            let urls = await Task.detached(priority: .userInitiated) {
                FolderScanner.videos(in: folder, recursive: recurse)
            }.value
            guard let self else { return }
            self.isScanning = false
            if urls.isEmpty {
                self.alertMessage = "No compatible videos were found in \(folder.lastPathComponent)."
            } else {
                self.add(urls: urls)
            }
        }
    }

    func add(urls: [URL]) {
        let current = Set(items.map { $0.url.standardizedFileURL.path })
        let newURLs = urls
            .map(\.standardizedFileURL)
            .filter(MediaProbe.looksLikeVideo)
            .filter { !current.contains($0.path) }
        guard !newURLs.isEmpty else { return }

        let newItems = newURLs.map(VideoItem.init(url:))
        items.append(contentsOf: newItems)
        // Folder scans can find thousands of clips. Keep the probe side bounded
        // instead of opening every asset and file descriptor at once.
        Task { [weak self] in
            await self?.probe(items: newItems)
        }
    }

    func remove(_ id: UUID) {
        guard !isCompressing else { return }
        items.removeAll { $0.id == id }
    }

    func clearFinished() {
        guard !isCompressing else { return }
        items.removeAll { $0.state == .complete || $0.state == .cancelled }
    }

    func toggleAllVisible(_ selected: Bool) {
        let visibleIDs = Set(visibleItems.map(\.id))
        for index in items.indices where visibleIDs.contains(items[index].id) {
            if items[index].state == .ready { items[index].isSelected = selected }
        }
    }

    func applyPreset(_ preset: CompressionPreset) {
        recipe.apply(preset)
    }

    func markRecipeCustom() {
        if recipe.preset != .custom { recipe.preset = .custom }
    }

    func requestCompression() {
        guard !isCompressing else { return }
        guard selectedReadyCount > 0 else {
            alertMessage = "Choose at least one ready video first."
            return
        }
        guard export.mode == .sameFolder || export.folderURL != nil else {
            alertMessage = "Choose an export folder, or switch the destination to Same folder."
            return
        }
        if export.replaceOriginal {
            showReplaceConfirmation = true
        } else {
            startCompression()
        }
    }

    func startCompression() {
        guard !isCompressing else { return }
        let pending = items.filter { $0.isSelected && $0.state == .ready }
        guard !pending.isEmpty else { return }
        let recipe = recipe
        let export = export
        let lanes = performance.recommendedParallelism
        let jobs = pending.map { ($0.id, $0) }
        batchIDs = Set(pending.map(\.id))
        for id in batchIDs {
            update(id) { item in
                item.state = .ready
                item.phase = nil
                item.progress = 0
                item.outputURL = nil
                item.outputBytes = nil
                item.startedAt = nil
            }
        }
        isCancelling = false
        batchStartedAt = .now
        batchMediaRate = nil
        lastRateSample = nil
        startTelemetryClock()
        isCompressing = true

        batchTask = Task { [weak self, encoder] in
            guard let self else { return }
            await self.runBatch(jobs: jobs, lanes: lanes, recipe: recipe, export: export, encoder: encoder)
        }
    }

    func cancelCompression() {
        guard isCompressing, !isCancelling else { return }
        isCancelling = true
        // Do not wait for cooperative Task cancellation to reach AVFoundation.
        // This directly stops every active reader / writer, including one that
        // is waiting on a slow external drive during finalization.
        encoder.cancelAll()
        batchTask?.cancel()
        for id in batchIDs {
            update(id) { item in
                if item.state == .ready {
                    item.state = .cancelled
                    item.phase = nil
                } else if item.state == .encoding {
                    item.phase = .cancelling
                }
            }
        }
        refreshBatchTelemetry()
    }

    func reveal(_ url: URL?) {
        guard let url else { return }
        NSWorkspace.shared.activateFileViewerSelecting([url])
    }

    private func runBatch(
        jobs: [(UUID, VideoItem)],
        lanes: Int,
        recipe: CompressionRecipe,
        export: ExportOptions,
        encoder: TranscodeEngine
    ) async {
        await withTaskGroup(of: JobOutcome.self) { group in
            var nextIndex = 0
            let initialCount = min(lanes, jobs.count)
            for _ in 0..<initialCount {
                let job = jobs[nextIndex]
                nextIndex += 1
                enqueue(job: job, in: &group, recipe: recipe, export: export, encoder: encoder)
            }

            while let outcome = await group.next() {
                apply(outcome)
                if nextIndex < jobs.count, !Task.isCancelled {
                    let job = jobs[nextIndex]
                    nextIndex += 1
                    enqueue(job: job, in: &group, recipe: recipe, export: export, encoder: encoder)
                }
            }
        }
        if Task.isCancelled {
            for id in batchIDs {
                update(id) { item in
                    if item.state == .ready || item.state == .encoding { item.state = .cancelled }
                    item.phase = nil
                }
            }
        }
        stopTelemetryClock()
        isCancelling = false
        isCompressing = false
        batchTask = nil
    }

    private func enqueue(
        job: (UUID, VideoItem),
        in group: inout TaskGroup<JobOutcome>,
        recipe: CompressionRecipe,
        export: ExportOptions,
        encoder: TranscodeEngine
    ) {
        let id = job.0
        let item = job.1
        let model = self
        update(id) { current in
            current.state = .encoding
            current.phase = .preparing
            current.startedAt = .now
        }
        group.addTask {
            do {
                let result = try await encoder.transcode(item: item, recipe: recipe, export: export) { value in
                    Task { @MainActor in
                        model.receive(value, for: id)
                    }
                }
                return .success(id: id, result: result)
            } catch is CancellationError {
                return .cancelled(id: id)
            } catch let error as AlchemistError {
                if case .cancelled = error {
                    return .cancelled(id: id)
                }
                return .failure(id: id, message: error.localizedDescription)
            } catch {
                return .failure(id: id, message: error.localizedDescription)
            }
        }
    }

    private func apply(_ outcome: JobOutcome) {
        switch outcome {
        case .success(let id, let result):
            update(id) { item in
                item.state = .complete
                item.phase = nil
                item.progress = 1
                item.outputURL = result.outputURL
                item.outputBytes = result.outputBytes
            }
        case .failure(let id, let message):
            update(id) { item in
                item.state = .failed(message)
                item.phase = nil
            }
        case .cancelled(let id):
            update(id) { item in
                item.state = .cancelled
                item.phase = nil
            }
        }
        refreshBatchTelemetry()
    }

    private func receive(_ engineUpdate: TranscodeUpdate, for id: UUID) {
        update(id) { item in
            guard item.state == .encoding else { return }
            // Video and audio feed queues can report in either order. Once an
            // item has moved into finalization, ignore an older media-time tick.
            if let current = item.phase,
               [.finalizing, .committing, .cancelling].contains(current),
               [.encoding, .finishingAudio, .preparing].contains(engineUpdate.phase) {
                return
            }
            item.progress = max(item.progress, engineUpdate.progress)
            item.phase = engineUpdate.phase
        }
        refreshBatchTelemetry()
    }

    private var batchItems: [VideoItem] {
        items.filter { batchIDs.contains($0.id) }
    }

    private var totalBatchMediaSeconds: Double {
        batchItems.reduce(0) { $0 + mediaWeight(for: $1) }
    }

    private var processedBatchMediaSeconds: Double {
        batchItems.reduce(0) { $0 + (mediaWeight(for: $1) * effectiveProgress(for: $1)) }
    }

    private func mediaWeight(for item: VideoItem) -> Double {
        max(0.01, item.metadata?.duration ?? 1)
    }

    private func effectiveProgress(for item: VideoItem) -> Double {
        switch item.state {
        case .complete, .failed, .cancelled: return 1
        default: break
        }
        if item.phase == .finalizing || item.phase == .committing { return 1 }
        return min(1, max(0, item.progress))
    }

    private func startTelemetryClock() {
        telemetryTimer?.invalidate()
        telemetryTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.refreshBatchTelemetry()
            }
        }
    }

    private func stopTelemetryClock() {
        telemetryTimer?.invalidate()
        telemetryTimer = nil
        lastRateSample = nil
    }

    private func refreshBatchTelemetry() {
        let now = Date()
        telemetryTick = now
        guard isCompressing else { return }
        let processed = processedBatchMediaSeconds
        guard let last = lastRateSample else {
            lastRateSample = (now, processed)
            return
        }
        let wallDelta = now.timeIntervalSince(last.date)
        guard wallDelta >= 0.75 else { return }
        let mediaDelta = processed - last.mediaSeconds
        lastRateSample = (now, processed)
        guard mediaDelta > 0 else { return }
        let instantaneous = mediaDelta / wallDelta
        if let current = batchMediaRate {
            batchMediaRate = (current * 0.75) + (instantaneous * 0.25)
        } else {
            batchMediaRate = instantaneous
        }
    }

    private func update(_ id: UUID, transform: (inout VideoItem) -> Void) {
        guard let index = items.firstIndex(where: { $0.id == id }) else { return }
        transform(&items[index])
    }

    private func probe(items: [VideoItem]) async {
        let lanes = min(4, items.count)
        guard lanes > 0 else { return }
        await withTaskGroup(of: ProbeOutcome.self) { group in
            var nextIndex = 0
            for _ in 0..<lanes {
                enqueueProbe(items[nextIndex], in: &group)
                nextIndex += 1
            }
            while let outcome = await group.next() {
                switch outcome {
                case .success(let id, let metadata):
                    update(id) { current in
                        current.metadata = metadata
                        if metadata.isHDR {
                            current.isSelected = false
                            current.state = .failed("HDR is protected: this SDR recipe will not flatten its color.")
                        } else {
                            current.state = .ready
                        }
                    }
                case .failure(let id, let message):
                    update(id) { current in
                        current.state = .failed(message)
                    }
                }
                if nextIndex < items.count {
                    enqueueProbe(items[nextIndex], in: &group)
                    nextIndex += 1
                }
            }
        }
    }

    private func enqueueProbe(_ item: VideoItem, in group: inout TaskGroup<ProbeOutcome>) {
        group.addTask {
            do {
                return .success(id: item.id, metadata: try await MediaProbe.inspect(item.url))
            } catch {
                return .failure(id: item.id, message: error.localizedDescription)
            }
        }
    }

    private func resolutionGroup(for metadata: VideoMetadata?) -> String {
        guard let metadata else { return "Other" }
        switch metadata.verticalResolution {
        case 2_000...: return "4K"
        case 1_300..<2_000: return "1440p"
        case 900..<1_300: return "1080p"
        case 600..<900: return "720p"
        case 400..<600: return "480p"
        default: return "Other"
        }
    }
}

private enum JobOutcome {
    case success(id: UUID, result: TranscodeResult)
    case failure(id: UUID, message: String)
    case cancelled(id: UUID)
}

private enum ProbeOutcome {
    case success(id: UUID, metadata: VideoMetadata)
    case failure(id: UUID, message: String)
}
