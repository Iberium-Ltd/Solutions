import SwiftUI

@main
struct AlchemistApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            AppShellView()
                .environmentObject(model)
                .frame(minWidth: 1_120, minHeight: 720)
                .task { model.loadHardwareStatus() }
        }
        .windowStyle(.hiddenTitleBar)
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Add Videos…") { model.chooseFiles() }
                    .keyboardShortcut("o", modifiers: .command)
                Button("Scan Folder…") { model.chooseFolderAndScan() }
                    .keyboardShortcut("o", modifiers: [.command, .shift])
            }
        }
    }
}
