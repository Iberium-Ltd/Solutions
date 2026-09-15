import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct AppShellView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ZStack {
            AuroraBackdrop()
            HStack(spacing: 0) {
                SidebarView()
                    .frame(width: 248)
                Rectangle()
                    .fill(Color.white.opacity(0.075))
                    .frame(width: 1)
                WorkspaceView()
            }
        }
        .preferredColorScheme(.dark)
        .alert("Alchemist", isPresented: Binding(
            get: { model.alertMessage != nil },
            set: { if !$0 { model.alertMessage = nil } }
        )) {
            Button("OK", role: .cancel) { model.alertMessage = nil }
        } message: {
            Text(model.alertMessage ?? "")
        }
        .alert("Replace the original files?", isPresented: $model.showReplaceConfirmation) {
            Button("Replace originals", role: .destructive) { model.startCompression() }
            Button("Keep originals", role: .cancel) { }
        } message: {
            Text("Each video will encode to a hidden staging file first, then replace its original only after the new file is complete. This cannot be undone from Alchemist.")
        }
    }
}

private struct SidebarView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 11) {
                AlchemistMark(size: 33)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Alchemist")
                        .font(.system(size: 19, weight: .bold, design: .rounded))
                    Text("VIDEO FORGE")
                        .font(.system(size: 9, weight: .bold, design: .rounded))
                        .tracking(1.6)
                        .foregroundStyle(Color.mutedText)
                }
            }
            .padding(.horizontal, 23)
            .padding(.top, 28)
            .padding(.bottom, 30)

            VStack(spacing: 9) {
                SidebarPrimaryButton(title: "Add videos", icon: "plus") { model.chooseFiles() }
                SidebarSecondaryButton(title: "Scan a folder", icon: "folder.badge.plus") { model.chooseFolderAndScan() }
            }
            .padding(.horizontal, 16)

            VStack(alignment: .leading, spacing: 11) {
                SidebarSectionLabel("LIBRARY")
                SidebarStat(icon: "film.stack", title: "In queue", value: "\(model.items.count)")
                SidebarStat(icon: "checkmark.circle", title: "Finished", value: "\(model.completedCount)")
                SidebarStat(icon: "arrow.down.right.and.arrow.up.left", title: "Saved", value: ByteCountFormatter.alchemistString(model.completedSavingsBytes))
            }
            .padding(.horizontal, 22)
            .padding(.top, 32)

            Spacer(minLength: 22)

            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 7) {
                    Circle()
                        .fill(model.hardwareStatus.hevcHardwareEncoderAvailable ? Color.mintAccent : Color.orange)
                        .frame(width: 7, height: 7)
                        .shadow(color: (model.hardwareStatus.hevcHardwareEncoderAvailable ? Color.mintAccent : Color.orange).opacity(0.65), radius: 6)
                    Text(model.hardwareStatus.label)
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(Color.primary.opacity(0.83))
                }
                Text("Apple Silicon hardware encode")
                    .font(.system(size: 10))
                    .foregroundStyle(Color.mutedText)
                    .lineLimit(1)
            }
            .padding(14)
            .background(Color.white.opacity(0.055), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(Color.white.opacity(0.07), lineWidth: 1)
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 20)
        }
        .background(Color.sidebarBackground.opacity(0.86))
    }
}

private struct WorkspaceView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            WorkspaceHeader()
            if model.items.isEmpty {
                EmptyQueueView()
                    .padding(.horizontal, 32)
                    .padding(.bottom, 28)
            } else {
                QueueWorkspace()
                    .padding(.horizontal, 26)
                    .padding(.bottom, 20)
            }
        }
    }
}

private struct WorkspaceHeader: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(alignment: .center) {
            VStack(alignment: .leading, spacing: 4) {
                Text(model.isCompressing ? "Forging smaller files" : "Video compression, refined.")
                    .font(.system(size: 26, weight: .bold, design: .rounded))
                Text(model.isCompressing
                    ? liveSubtitle
                    : "Drop a batch, pick a recipe, let the media engines work.")
                    .font(.system(size: 13))
                    .monospacedDigit()
                    .contentTransition(.numericText())
                    .foregroundStyle(Color.mutedText)
            }
            Spacer()
            if !model.items.isEmpty {
                HardwarePill()
            }
        }
        .padding(.horizontal, 30)
        .padding(.top, 29)
        .padding(.bottom, 21)
    }

    private var liveSubtitle: String {
        let laneText = "\(model.activeLanes) active \(model.activeLanes == 1 ? "lane" : "lanes")"
        let completedText = "\(model.batchCompletedCount)/\(model.batchIDs.count) complete"
        switch model.batchPhase {
        case .cancelling:
            return "\(laneText) · \(model.batchStatusText) · \(model.batchElapsedText) elapsed"
        case .finalizing, .committing, .finishingAudio:
            return "\(laneText) · \(model.batchStatusText) · \(model.batchElapsedText) elapsed"
        case .preparing:
            return "\(laneText) · \(model.batchStatusText)"
        case .encoding, .none:
            var parts = [laneText, completedText, "\(Int(model.batchProgress * 100))%"]
            if let speed = model.batchSpeedText { parts.append(speed) }
            if let eta = model.batchETAText { parts.append(eta) }
            return parts.joined(separator: " · ")
        }
    }
}

private struct HardwarePill: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "cpu")
            HStack(spacing: 3) {
                ForEach(0..<model.performance.recommendedParallelism, id: \.self) { lane in
                    Capsule()
                        .fill(lane < model.activeLanes ? Color.cyanAccent : Color.white.opacity(0.14))
                        .frame(width: 7, height: 4)
                        .shadow(color: lane < model.activeLanes ? Color.cyanAccent.opacity(0.72) : .clear, radius: 4)
                }
            }
            .animation(.spring(response: 0.32, dampingFraction: 0.72), value: model.activeLanes)
            Text(model.performance == .max ? "M4 Max mode" : "Apple Silicon")
                .font(.system(size: 12, weight: .semibold))
        }
        .foregroundStyle(Color.cyanAccent)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color.cyanAccent.opacity(0.11), in: Capsule())
        .overlay { Capsule().stroke(Color.cyanAccent.opacity(0.20), lineWidth: 1) }
    }
}

private struct EmptyQueueView: View {
    @EnvironmentObject private var model: AppModel
    @State private var isTargeted = false

    var body: some View {
        VStack(spacing: 22) {
            Spacer(minLength: 8)
            CompressionOrb(isActive: isTargeted)
                .frame(width: 154, height: 154)
            VStack(spacing: 8) {
                Text(isTargeted ? "Drop to add the batch" : "Start with your videos")
                    .font(.system(size: 24, weight: .bold, design: .rounded))
                Text("Drag files here, choose them from Finder, or scan a whole folder.\nAlchemist reads every resolution before it touches a pixel.")
                    .font(.system(size: 14))
                    .foregroundStyle(Color.mutedText)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
            }
            HStack(spacing: 11) {
                Button(action: model.chooseFiles) {
                    Label("Choose videos", systemImage: "plus")
                }
                .buttonStyle(PrimaryButtonStyle())
                Button(action: model.chooseFolderAndScan) {
                    Label("Scan folder", systemImage: "folder")
                }
                .buttonStyle(SecondaryButtonStyle())
            }
            Spacer(minLength: 12)
            HStack(spacing: 18) {
                EmptyFeature(icon: "bolt.fill", text: "Hardware encode")
                EmptyFeature(icon: "rectangle.3.group", text: "Batch by resolution")
                EmptyFeature(icon: "arrow.triangle.2.circlepath", text: "Safe replace")
            }
        }
        .padding(36)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .fill(isTargeted ? Color.cyanAccent.opacity(0.11) : Color.cardBackground)
        )
        .overlay {
            RoundedRectangle(cornerRadius: 28, style: .continuous)
                .stroke(
                    isTargeted ? Color.cyanAccent.opacity(0.85) : Color.white.opacity(0.11),
                    style: StrokeStyle(lineWidth: isTargeted ? 2 : 1, dash: isTargeted ? [8, 5] : [])
                )
        }
        .animation(.spring(response: 0.34, dampingFraction: 0.78), value: isTargeted)
        .onDrop(of: [.fileURL], isTargeted: $isTargeted) { providers in
            loadDroppedURLs(providers, into: model)
        }
    }
}

private struct QueueWorkspace: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(alignment: .top, spacing: 18) {
            QueuePanel()
                .frame(minWidth: 520, maxWidth: .infinity)
            RecipePanel()
                .frame(width: 332)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct QueuePanel: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Queue")
                        .font(.system(size: 17, weight: .bold, design: .rounded))
                    Text("\(model.selectedReadyCount) selected · \(ByteCountFormatter.alchemistString(model.selectedSourceBytes)) source")
                        .font(.system(size: 11))
                        .foregroundStyle(Color.mutedText)
                }
                Spacer()
                Menu {
                    Picker("Resolution", selection: $model.selectedResolutionGroup) {
                        ForEach(model.resolutionGroups, id: \.self) { group in
                            Text(group).tag(group)
                        }
                    }
                } label: {
                    Label(model.selectedResolutionGroup, systemImage: "rectangle.3.group")
                }
                .menuStyle(.borderlessButton)
                .fixedSize()
                Menu {
                    Button("Select visible") { model.toggleAllVisible(true) }
                    Button("Deselect visible") { model.toggleAllVisible(false) }
                    Divider()
                    Button("Clear finished") { model.clearFinished() }
                } label: {
                    Image(systemName: "ellipsis")
                        .frame(width: 26, height: 26)
                }
                .menuStyle(.borderlessButton)
            }
            .padding(.horizontal, 19)
            .padding(.vertical, 16)

            Rectangle().fill(Color.white.opacity(0.075)).frame(height: 1)

            ScrollView {
                LazyVStack(spacing: 8) {
                    ForEach(model.visibleItems) { item in
                        VideoRow(item: item)
                            .transition(.asymmetric(
                                insertion: .move(edge: .bottom).combined(with: .opacity),
                                removal: .opacity
                            ))
                    }
                }
                .padding(11)
            }
            .animation(.spring(response: 0.42, dampingFraction: 0.84), value: model.items.map(\.id))

            Rectangle().fill(Color.white.opacity(0.075)).frame(height: 1)
            QueueFooter()
        }
        .background(Color.cardBackground, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.white.opacity(0.10), lineWidth: 1) }
    }
}

private struct VideoRow: View {
    @EnvironmentObject private var model: AppModel
    let item: VideoItem

    private var selectionBinding: Binding<Bool> {
        Binding(
            get: { model.items.first(where: { $0.id == item.id })?.isSelected ?? false },
            set: { desired in
                guard let index = model.items.firstIndex(where: { $0.id == item.id }), model.items[index].state == .ready else { return }
                model.items[index].isSelected = desired
            }
        )
    }

    var body: some View {
        HStack(spacing: 12) {
            Toggle("", isOn: selectionBinding)
                .toggleStyle(.checkbox)
                .labelsHidden()
                .disabled(item.state != .ready)
                .opacity(item.state == .ready ? 1 : 0.54)
            VideoGlyph(state: item.state, phase: item.phase)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 7) {
                    Text(item.displayName)
                        .font(.system(size: 13, weight: .semibold))
                        .lineLimit(1)
                    if item.state == .complete, let savings = item.savingsFraction {
                        Text("−\(Int(savings * 100))%")
                            .font(.system(size: 10, weight: .bold, design: .rounded))
                            .foregroundStyle(Color.mintAccent)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.mintAccent.opacity(0.12), in: Capsule())
                    }
                }
                if let metadata = item.metadata {
                    Text("\(metadata.resolutionText)  ·  \(metadata.durationText)  ·  \(metadata.fpsText)\(metadata.isHDR ? "  ·  HDR" : "")  ·  \(metadata.sizeText)")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(Color.mutedText)
                        .lineLimit(1)
                } else if case .failed(let message) = item.state {
                    Text(message)
                        .font(.system(size: 10))
                        .foregroundStyle(Color.red.opacity(0.90))
                        .lineLimit(1)
                } else {
                    Text("Reading video metadata…")
                        .font(.system(size: 11))
                        .foregroundStyle(Color.mutedText)
                }
                if item.state == .encoding {
                    VStack(spacing: 4) {
                        EnergyRail(progress: item.progress, phase: item.phase)
                        HStack(spacing: 5) {
                            Image(systemName: item.phase?.systemImage ?? "bolt.fill")
                            Text(item.phase?.label ?? "Compressing")
                            Spacer()
                            if item.phase == .encoding || item.phase == .finishingAudio || item.phase == .preparing {
                                Text("\(Int(item.progress * 100))%")
                                    .contentTransition(.numericText())
                            } else {
                                Text("drive flush")
                            }
                        }
                        .font(.system(size: 9.5, weight: .semibold, design: .monospaced))
                        .foregroundStyle(item.phase == .cancelling ? Color.orange : Color.mutedText)
                    }
                    .padding(.top, 3)
                }
            }
            Spacer(minLength: 4)
            VStack(alignment: .trailing, spacing: 6) {
                StatusPill(state: item.state, phase: item.phase)
                if item.state == .complete {
                    Button { model.reveal(item.outputURL) } label: {
                        Image(systemName: "magnifyingglass")
                            .font(.system(size: 11, weight: .bold))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Color.mutedText)
                    .help("Reveal in Finder")
                } else if isRemovable {
                    Button { model.remove(item.id) } label: {
                        Image(systemName: "xmark")
                            .font(.system(size: 10, weight: .bold))
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(Color.mutedText)
                    .help("Remove")
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .background(rowBackground, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 13, style: .continuous)
                .stroke(item.isSelected ? Color.cyanAccent.opacity(0.22) : Color.white.opacity(0.055), lineWidth: 1)
        }
    }

    private var rowBackground: Color {
        switch item.state {
        case .encoding:
            if item.phase == .finalizing || item.phase == .committing {
                Color.violetAccent.opacity(0.085)
            } else if item.phase == .cancelling {
                Color.orange.opacity(0.075)
            } else {
                Color.cyanAccent.opacity(0.08)
            }
        case .complete: Color.mintAccent.opacity(0.055)
        case .failed: Color.red.opacity(0.06)
        default: Color.white.opacity(0.037)
        }
    }

    private var isRemovable: Bool {
        switch item.state {
        case .ready, .failed, .cancelled: true
        default: false
        }
    }
}

private struct QueueFooter: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(spacing: 12) {
            Button(action: model.chooseFiles) {
                Label("Add more", systemImage: "plus")
                    .font(.system(size: 12, weight: .semibold))
            }
            .buttonStyle(.plain)
            .foregroundStyle(Color.cyanAccent)
            Spacer()
            if model.isCompressing {
                BatchProgress()
                if model.isCancelling {
                    HStack(spacing: 7) {
                        ProgressView()
                            .controlSize(.small)
                        Text("Stopping…")
                    }
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color.orange)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color.orange.opacity(0.10), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                } else {
                    Button("Cancel batch", role: .destructive, action: model.cancelCompression)
                        .buttonStyle(SecondaryButtonStyle(compact: true))
                }
            } else {
                Button(action: model.requestCompression) {
                    Label("Compress \(model.selectedReadyCount)", systemImage: "bolt.fill")
                }
                .buttonStyle(PrimaryButtonStyle(compact: true))
                .disabled(model.selectedReadyCount == 0)
            }
        }
        .padding(.horizontal, 17)
        .padding(.vertical, 13)
    }
}

private struct BatchProgress: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .trailing, spacing: 3) {
            HStack(spacing: 8) {
                if model.batchPhase == .finalizing || model.batchPhase == .committing || model.batchPhase == .finishingAudio {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Color.violetAccent)
                    Text(model.batchStatusText)
                        .font(.system(size: 10.5, weight: .semibold))
                        .foregroundStyle(Color.violetAccent)
                } else {
                    EnergyRail(progress: model.batchProgress, phase: model.batchPhase)
                        .frame(width: 96)
                    Text("\(Int(model.batchProgress * 100))%")
                        .font(.system(size: 11, weight: .bold, design: .monospaced))
                        .contentTransition(.numericText())
                        .foregroundStyle(Color.mintAccent)
                }
            }
            HStack(spacing: 7) {
                if let speed = model.batchSpeedText { Text(speed) }
                if let eta = model.batchETAText { Text(eta) }
                Text("\(model.batchElapsedText) elapsed")
            }
            .font(.system(size: 9.5, weight: .medium, design: .monospaced))
            .foregroundStyle(Color.mutedText)
            .contentTransition(.numericText())
        }
    }
}

private struct RecipePanel: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Recipe")
                            .font(.system(size: 17, weight: .bold, design: .rounded))
                        Text("Simple up front. Exact underneath.")
                            .font(.system(size: 11))
                            .foregroundStyle(Color.mutedText)
                    }
                    Spacer()
                    Image(systemName: "slider.horizontal.3")
                        .foregroundStyle(Color.cyanAccent)
                }

                SettingCard(title: "Compression") {
                    VStack(spacing: 6) {
                        ForEach(CompressionPreset.allCases) { preset in
                            Button {
                                model.applyPreset(preset)
                            } label: {
                                HStack(spacing: 9) {
                                    Circle()
                                        .fill(model.recipe.preset == preset ? Color.cyanAccent : Color.white.opacity(0.13))
                                        .frame(width: 7, height: 7)
                                    VStack(alignment: .leading, spacing: 1) {
                                        Text(preset.title)
                                            .font(.system(size: 12, weight: .semibold))
                                        if preset == model.recipe.preset {
                                            Text(preset.detail)
                                                .font(.system(size: 10))
                                                .foregroundStyle(Color.mutedText)
                                        }
                                    }
                                    Spacer()
                                }
                                .padding(.horizontal, 10)
                                .padding(.vertical, model.recipe.preset == preset ? 8 : 6)
                                .background(model.recipe.preset == preset ? Color.cyanAccent.opacity(0.10) : .clear, in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                SettingCard(title: "Quality", trailing: model.recipe.qualityLabel) {
                    Slider(value: Binding(
                        get: { model.recipe.quality },
                        set: { model.recipe.quality = $0; model.markRecipeCustom() }
                    ), in: 0.12...0.96)
                    .tint(Color.cyanAccent)
                    HStack {
                        Text("Smaller file")
                        Spacer()
                        Text("More detail")
                    }
                    .font(.system(size: 10))
                    .foregroundStyle(Color.mutedText)
                }

                SettingCard(title: "Resolution") {
                    Picker("Resolution", selection: Binding(
                        get: { model.recipe.resolution },
                        set: { model.recipe.resolution = $0; model.markRecipeCustom() }
                    )) {
                        ForEach(ResolutionOption.allCases) { option in
                            Text(option.title).tag(option)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                ExportCard()
                PerformanceCard()
                AdvancedCard()
            }
            .padding(16)
        }
        .background(Color.cardBackground, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Color.white.opacity(0.10), lineWidth: 1) }
    }
}

private struct ExportCard: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        SettingCard(title: "Export") {
            Picker("Destination", selection: Binding(
                get: { model.export.mode },
                set: { mode in
                    model.export.mode = mode
                    if mode == .sameFolder {
                        model.export.replaceOriginal = true
                    } else {
                        model.export.replaceOriginal = false
                        model.export.keepOriginalName = true
                        model.export.collisionPolicy = .overwrite
                    }
                }
            )) {
                ForEach(DestinationMode.allCases) { option in
                    Text(option.title).tag(option)
                }
            }
            .labelsHidden()
            .pickerStyle(.segmented)
            if model.export.mode == .chosenFolder {
                Button(action: model.chooseExportFolder) {
                    HStack {
                        Image(systemName: "folder")
                        Text(model.export.folderURL?.lastPathComponent ?? "Choose export folder")
                            .lineLimit(1)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.system(size: 10, weight: .bold))
                    }
                    .font(.system(size: 11, weight: .medium))
                    .padding(9)
                    .background(Color.white.opacity(0.055), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
                }
                .buttonStyle(.plain)
                Label("Uses the original file name · replaces prior output", systemImage: "text.badge.checkmark")
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(Color.mintAccent)
            } else {
                Toggle("Replace originals after success", isOn: Binding(
                    get: { model.export.replaceOriginal },
                    set: { model.export.replaceOriginal = $0 }
                ))
                .font(.system(size: 11, weight: .medium))
                .toggleStyle(.switch)
                if model.export.replaceOriginal {
                    Label("Replaces the source only after the new file is finished", systemImage: "checkmark.shield")
                        .font(.system(size: 10))
                        .foregroundStyle(Color.mintAccent)
                } else {
                    Text("Outputs use “· Alchemist” to keep the source safe.")
                        .font(.system(size: 10))
                        .foregroundStyle(Color.mutedText)
                }
            }
        }
    }
}

private struct PerformanceCard: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        SettingCard(title: "Power mode") {
            Picker("Power mode", selection: $model.performance) {
                ForEach(PerformanceMode.allCases) { mode in
                    Text(mode.title).tag(mode)
                }
            }
            .labelsHidden()
            .pickerStyle(.segmented)
            Text(model.performance.detail)
                .font(.system(size: 10))
                .foregroundStyle(model.performance == .max ? Color.orange : Color.mutedText)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct AdvancedCard: View {
    @EnvironmentObject private var model: AppModel
    @State private var isExpanded = false
    @State private var bitrateText = ""

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            VStack(alignment: .leading, spacing: 12) {
                Picker("Codec", selection: Binding(
                    get: { model.recipe.codec },
                    set: { model.recipe.codec = $0; model.markRecipeCustom() }
                )) {
                    ForEach(VideoCodec.allCases) { codec in
                        Text(codec.title).tag(codec)
                    }
                }
                .font(.system(size: 11))
                Picker("Container", selection: Binding(
                    get: { model.recipe.container },
                    set: { model.recipe.container = $0; model.markRecipeCustom() }
                )) {
                    ForEach(ContainerFormat.allCases) { format in
                        Text(format.title).tag(format)
                    }
                }
                .font(.system(size: 11))
                HStack {
                    Text("Target bitrate")
                        .font(.system(size: 11))
                    Spacer()
                    TextField("Auto", text: Binding(
                        get: {
                            if let bitrate = model.recipe.targetBitrateMbps {
                                return String(format: "%.1f", bitrate)
                            }
                            return bitrateText
                        },
                        set: { newValue in
                            bitrateText = newValue
                            model.recipe.targetBitrateMbps = Double(newValue)
                            model.markRecipeCustom()
                        }
                    ))
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 62)
                    Text("Mb/s")
                        .font(.system(size: 10))
                        .foregroundStyle(Color.mutedText)
                }
                Stepper("Keyframe every \(model.recipe.keyframeSeconds)s", value: Binding(
                    get: { model.recipe.keyframeSeconds },
                    set: { model.recipe.keyframeSeconds = $0; model.markRecipeCustom() }
                ), in: 1...10)
                .font(.system(size: 11))
                Stepper("AAC audio \(model.recipe.audioBitrateKbps) kb/s", value: Binding(
                    get: { model.recipe.audioBitrateKbps },
                    set: { model.recipe.audioBitrateKbps = $0; model.markRecipeCustom() }
                ), in: 64...320, step: 32)
                .font(.system(size: 11))
            }
            .padding(.top, 10)
        } label: {
            HStack {
                Text("Advanced")
                    .font(.system(size: 12, weight: .semibold))
                Spacer()
                Text(model.recipe.codec.shortTitle)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(Color.mutedText)
            }
        }
        .padding(13)
        .background(Color.white.opacity(0.042), in: RoundedRectangle(cornerRadius: 13, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 13, style: .continuous).stroke(Color.white.opacity(0.08), lineWidth: 1) }
    }
}

private struct SettingCard<Content: View>: View {
    let title: String
    var trailing: String? = nil
    @ViewBuilder let content: Content

    init(title: String, trailing: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.trailing = trailing
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(title)
                    .font(.system(size: 12, weight: .bold))
                Spacer()
                if let trailing {
                    Text(trailing)
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(Color.cyanAccent)
                }
            }
            content
        }
        .padding(13)
        .background(Color.white.opacity(0.042), in: RoundedRectangle(cornerRadius: 13, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 13, style: .continuous).stroke(Color.white.opacity(0.08), lineWidth: 1) }
    }
}

private struct VideoGlyph: View {
    let state: JobState
    let phase: EncodingPhase?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(glyphColor.opacity(0.16))
            Image(systemName: icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(glyphColor)
                .symbolEffect(
                    .pulse,
                    options: .repeating,
                    isActive: state == .encoding && !reduceMotion
                )
        }
        .frame(width: 36, height: 36)
        .animation(.spring(response: 0.35, dampingFraction: 0.68), value: state)
    }

    private var icon: String {
        switch state {
        case .complete: "checkmark"
        case .failed: "exclamationmark"
        case .encoding: phase?.systemImage ?? "bolt.fill"
        case .analyzing: "ellipsis"
        default: "play.rectangle.fill"
        }
    }

    private var glyphColor: Color {
        switch state {
        case .complete: .mintAccent
        case .failed: .red
        case .encoding: .cyanAccent
        default: .violetAccent
        }
    }
}

private struct StatusPill: View {
    let state: JobState
    let phase: EncodingPhase?

    var body: some View {
        Text(state == .encoding ? (phase?.label ?? state.label) : state.label)
            .font(.system(size: 10, weight: .bold, design: .rounded))
            .foregroundStyle(color)
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(color.opacity(0.12), in: Capsule())
    }

    private var color: Color {
        switch state {
        case .ready: return .mutedText
        case .analyzing: return .orange
        case .encoding:
            if phase == .finalizing || phase == .committing { return .violetAccent }
            if phase == .cancelling { return .orange }
            return .cyanAccent
        case .complete: return .mintAccent
        case .failed: return .red
        case .cancelled: return .orange
        }
    }
}

/// The active visual is deliberately small and GPU-cheap: it moves only inside
/// the progress rail, leaving CPU and media engines available for compression.
private struct EnergyRail: View {
    let progress: Double
    let phase: EncodingPhase?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shimmering = false

    private var isFinishing: Bool {
        phase == .finalizing || phase == .committing || phase == .cancelling
    }

    var body: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            let filled = Swift.max(5, width * min(1, max(0, progress)))
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.white.opacity(0.10))
                if isFinishing {
                    LinearGradient(
                        colors: [Color.clear, Color.violetAccent.opacity(0.92), Color.cyanAccent.opacity(0.92), Color.clear],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                    .frame(width: width * 0.65)
                    .offset(x: reduceMotion ? width * 0.18 : (shimmering ? width : -width * 0.65))
                    .mask(Capsule())
                } else {
                    Capsule()
                        .fill(LinearGradient(colors: [.cyanAccent, .violetAccent], startPoint: .leading, endPoint: .trailing))
                        .frame(width: filled)
                        .shadow(color: Color.cyanAccent.opacity(0.34), radius: 5)
                    Circle()
                        .fill(Color.white.opacity(0.92))
                        .frame(width: 5, height: 5)
                        .shadow(color: Color.cyanAccent.opacity(0.90), radius: 5)
                        .offset(x: filled - 5)
                }
            }
        }
        .frame(height: 6)
        .animation(.easeOut(duration: 0.18), value: progress)
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.linear(duration: 1.15).repeatForever(autoreverses: false)) {
                shimmering = true
            }
        }
    }
}

private struct SidebarPrimaryButton: View {
    let title: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(.system(size: 13, weight: .bold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 11)
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.midnight)
        .background(LinearGradient(colors: [.cyanAccent, .violetAccent], startPoint: .leading, endPoint: .trailing), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .shadow(color: Color.cyanAccent.opacity(0.20), radius: 12, y: 5)
    }
}

private struct SidebarSecondaryButton: View {
    let title: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: icon)
                .font(.system(size: 12, weight: .semibold))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
        }
        .buttonStyle(.plain)
        .foregroundStyle(Color.primary.opacity(0.84))
        .background(Color.white.opacity(0.055), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Color.white.opacity(0.08), lineWidth: 1) }
    }
}

private struct SidebarSectionLabel: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text)
            .font(.system(size: 9, weight: .bold))
            .tracking(1.4)
            .foregroundStyle(Color.mutedText)
    }
}

private struct SidebarStat: View {
    let icon: String
    let title: String
    let value: String

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 12, weight: .medium))
                .frame(width: 16)
                .foregroundStyle(Color.violetAccent)
            Text(title)
                .font(.system(size: 12))
                .foregroundStyle(Color.primary.opacity(0.77))
            Spacer()
            Text(value)
                .font(.system(size: 11, weight: .bold, design: .monospaced))
                .foregroundStyle(Color.primary.opacity(0.92))
        }
    }
}

private struct EmptyFeature: View {
    let icon: String
    let text: String
    var body: some View {
        Label(text, systemImage: icon)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(Color.mutedText)
    }
}

private struct AlchemistMark: View {
    let size: CGFloat
    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.30, style: .continuous)
                .fill(LinearGradient(colors: [.cyanAccent, .violetAccent], startPoint: .topLeading, endPoint: .bottomTrailing))
            Image(systemName: "sparkles")
                .font(.system(size: size * 0.48, weight: .bold))
                .foregroundStyle(Color.midnight)
        }
        .frame(width: size, height: size)
        .shadow(color: Color.violetAccent.opacity(0.38), radius: 10, y: 3)
    }
}

private struct CompressionOrb: View {
    let isActive: Bool
    @State private var spinning = false
    @State private var breathing = false

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.cyanAccent.opacity(0.17), lineWidth: 1)
                .frame(width: 138, height: 138)
                .scaleEffect(breathing ? 1.05 : 0.92)
            Circle()
                .trim(from: 0.05, to: 0.68)
                .stroke(AngularGradient(colors: [.cyanAccent, .violetAccent, .cyanAccent.opacity(0)], center: .center), style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
                .frame(width: 117, height: 117)
                .rotationEffect(.degrees(spinning ? 360 : 0))
            Circle()
                .fill(RadialGradient(colors: [Color.cyanAccent.opacity(0.62), Color.violetAccent.opacity(0.28), Color.clear], center: .center, startRadius: 0, endRadius: 53))
                .frame(width: 106, height: 106)
                .scaleEffect(isActive ? 1.12 : 1)
            Image(systemName: isActive ? "arrow.down.to.line.compact" : "bolt.fill")
                .font(.system(size: 31, weight: .bold))
                .foregroundStyle(Color.white.opacity(0.94))
                .shadow(color: Color.cyanAccent.opacity(0.6), radius: 12)
        }
        .onAppear {
            withAnimation(.linear(duration: 5.5).repeatForever(autoreverses: false)) { spinning = true }
            withAnimation(.easeInOut(duration: 2.2).repeatForever(autoreverses: true)) { breathing = true }
        }
    }
}

private struct AuroraBackdrop: View {
    @State private var drifting = false

    var body: some View {
        ZStack {
            Color.midnight.ignoresSafeArea()
            GeometryReader { proxy in
                Circle()
                    .fill(Color.violetAccent.opacity(0.18))
                    .frame(width: proxy.size.width * 0.67)
                    .blur(radius: 85)
                    .offset(x: drifting ? proxy.size.width * 0.31 : proxy.size.width * 0.13, y: drifting ? -proxy.size.height * 0.42 : -proxy.size.height * 0.32)
                Circle()
                    .fill(Color.cyanAccent.opacity(0.13))
                    .frame(width: proxy.size.width * 0.57)
                    .blur(radius: 95)
                    .offset(x: drifting ? -proxy.size.width * 0.12 : -proxy.size.width * 0.01, y: drifting ? proxy.size.height * 0.38 : proxy.size.height * 0.48)
            }
            .allowsHitTesting(false)
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 13).repeatForever(autoreverses: true)) { drifting = true }
        }
    }
}

private struct PrimaryButtonStyle: ButtonStyle {
    var compact = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: compact ? 12 : 13, weight: .bold))
            .foregroundStyle(Color.midnight)
            .padding(.horizontal, compact ? 13 : 16)
            .padding(.vertical, compact ? 9 : 11)
            .background(LinearGradient(colors: [.cyanAccent, .violetAccent], startPoint: .leading, endPoint: .trailing), in: RoundedRectangle(cornerRadius: compact ? 10 : 11, style: .continuous))
            .opacity(configuration.isPressed ? 0.73 : 1)
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

private struct SecondaryButtonStyle: ButtonStyle {
    var compact = false

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: compact ? 12 : 13, weight: .semibold))
            .foregroundStyle(Color.primary.opacity(0.88))
            .padding(.horizontal, compact ? 12 : 15)
            .padding(.vertical, compact ? 8 : 10)
            .background(Color.white.opacity(configuration.isPressed ? 0.11 : 0.07), in: RoundedRectangle(cornerRadius: compact ? 10 : 11, style: .continuous))
            .overlay { RoundedRectangle(cornerRadius: compact ? 10 : 11, style: .continuous).stroke(Color.white.opacity(0.10), lineWidth: 1) }
            .scaleEffect(configuration.isPressed ? 0.98 : 1)
    }
}

private extension Color {
    static let midnight = Color(red: 0.040, green: 0.051, blue: 0.086)
    static let sidebarBackground = Color(red: 0.055, green: 0.066, blue: 0.108)
    static let cardBackground = Color(red: 0.075, green: 0.088, blue: 0.139).opacity(0.91)
    static let cyanAccent = Color(red: 0.31, green: 0.90, blue: 0.95)
    static let violetAccent = Color(red: 0.62, green: 0.48, blue: 1.0)
    static let mintAccent = Color(red: 0.36, green: 0.95, blue: 0.65)
    static let mutedText = Color.white.opacity(0.48)
}

private func loadDroppedURLs(_ providers: [NSItemProvider], into model: AppModel) -> Bool {
    let group = DispatchGroup()
    let lock = NSLock()
    var urls: [URL] = []
    for provider in providers {
        group.enter()
        provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, _ in
            defer { group.leave() }
            if let data = item as? Data, let url = URL(dataRepresentation: data, relativeTo: nil) {
                lock.lock()
                urls.append(url)
                lock.unlock()
            } else if let url = item as? URL {
                lock.lock()
                urls.append(url)
                lock.unlock()
            }
        }
    }
    group.notify(queue: .main) {
        Task { @MainActor in
            model.add(urls: urls)
        }
    }
    return true
}
