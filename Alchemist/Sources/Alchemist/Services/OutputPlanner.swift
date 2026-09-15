import AVFoundation
import Foundation

enum OutputPlanner {
    static func plan(
        for source: URL,
        options: ExportOptions,
        recipe: CompressionRecipe
    ) throws -> OutputPlan {
        let outputFolder = options.folder(for: source)
        let fileType = recipe.container.fileType(for: source)
        let outputExtension = recipe.container.fileExtension(for: source)
        let sourceExtension = source.pathExtension.lowercased()
        let originalBase = source.deletingPathExtension().lastPathComponent
        // A chosen export folder always mirrors the source filename. Re-running
        // a batch replaces its previous output rather than adding a branding
        // suffix or duplicate number. A same-folder export can only use the
        // identical name when it atomically replaces the source.
        let base: String
        if options.mode == .sameFolder {
            base = "\(originalBase) · Alchemist"
        } else {
            base = originalBase
        }

        if options.replaceOriginal {
            guard options.mode == .sameFolder,
                  ["mp4", "mov"].contains(sourceExtension),
                  sourceExtension == outputExtension else {
                throw AlchemistError.sourceCannotBeReplaced(source)
            }
            let temporaryName = ".\(originalBase).alchemist-\(UUID().uuidString).\(outputExtension)"
            return OutputPlan(
                stagingURL: outputFolder.appendingPathComponent(temporaryName),
                finalURL: source,
                replaceSource: true,
                collisionPolicy: .overwrite,
                fileType: fileType
            )
        }

        var destination = outputFolder.appendingPathComponent(base).appendingPathExtension(outputExtension)
        // If a custom destination happens to be the source's own folder, preserve
        // the source unless the user explicitly enabled Replace originals.
        if destination.standardizedFileURL == source.standardizedFileURL {
            destination = outputFolder
                .appendingPathComponent("\(originalBase) · Alchemist")
                .appendingPathExtension(outputExtension)
        }
        if options.collisionPolicy == .increment,
           FileManager.default.fileExists(atPath: destination.path) {
            destination = incrementedURL(from: destination)
        }
        let stagingName = ".\(destination.deletingPathExtension().lastPathComponent).alchemist-\(UUID().uuidString).\(outputExtension)"
        return OutputPlan(
            stagingURL: outputFolder.appendingPathComponent(stagingName),
            finalURL: destination,
            replaceSource: false,
            collisionPolicy: options.collisionPolicy,
            fileType: fileType
        )
    }

    static func finalize(_ plan: OutputPlan) throws -> URL {
        let fileManager = FileManager.default
        guard fileManager.fileExists(atPath: plan.stagingURL.path) else {
            throw AlchemistError.unableToCreateOutput(plan.stagingURL)
        }

        var destination = plan.finalURL
        while true {
            if fileManager.fileExists(atPath: destination.path) {
                if plan.replaceSource || plan.collisionPolicy == .overwrite {
                    _ = try fileManager.replaceItemAt(
                        destination,
                        withItemAt: plan.stagingURL,
                        backupItemName: nil,
                        options: []
                    )
                    revealInFinder(destination)
                    return destination
                }
                destination = incrementedURL(from: destination)
                continue
            }

            do {
                try fileManager.moveItem(at: plan.stagingURL, to: destination)
                // The staging filename begins with a dot, which makes macOS
                // assign its hidden file flag. Moving it does not clear that
                // flag, so explicitly make every completed export visible.
                revealInFinder(destination)
                return destination
            } catch {
                // Another parallel job can claim the same base name between the
                // existence check and move. Retry with a fresh incremented name.
                guard plan.collisionPolicy == .increment else { throw error }
                destination = incrementedURL(from: destination)
            }
        }
    }

    static func discardStagingFile(for plan: OutputPlan) {
        guard FileManager.default.fileExists(atPath: plan.stagingURL.path) else { return }
        try? FileManager.default.removeItem(at: plan.stagingURL)
    }

    private static func revealInFinder(_ url: URL) {
        var values = URLResourceValues()
        values.isHidden = false
        var visibleURL = url
        try? visibleURL.setResourceValues(values)
    }

    private static func incrementedURL(from initial: URL) -> URL {
        let folder = initial.deletingLastPathComponent()
        let base = initial.deletingPathExtension().lastPathComponent
        let ext = initial.pathExtension
        var index = 2
        var candidate = initial
        while FileManager.default.fileExists(atPath: candidate.path) {
            let incrementedName = base + " " + String(index)
            candidate = folder.appendingPathComponent(incrementedName).appendingPathExtension(ext)
            index += 1
        }
        return candidate
    }
}
