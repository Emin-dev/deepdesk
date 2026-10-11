#if os(macOS)
import SwiftUI
import AppKit

@MainActor
final class DeepdeskAppDelegate: NSObject, NSApplicationDelegate {
    weak var engine: EngineSupervisor?
    weak var inference: InferenceSupervisor?
    private var terminating = false

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if terminating { return .terminateLater }
        guard engine?.ownsRunningProcess == true || inference?.ownsRunningProcess == true else { return .terminateNow }
        terminating = true
        Task { @MainActor in
            await self.engine?.stopAndWait()
            await self.inference?.stopAndWait()
            let stopped = self.engine?.ownsRunningProcess != true && self.inference?.ownsRunningProcess != true
            if !stopped { self.terminating = false }
            sender.reply(toApplicationShouldTerminate: stopped)
        }
        return .terminateLater
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

@main
struct DeepdeskApp: App {
    @NSApplicationDelegateAdaptor(DeepdeskAppDelegate.self) private var delegate
    @StateObject private var store = ResearchStore()
    @StateObject private var engine = EngineSupervisor()
    @StateObject private var models = ModelManager()
    @StateObject private var identity = LocalIdentityManager()
    @StateObject private var inference = InferenceSupervisor()

    var body: some Scene {
        Window("Deepdesk", id: "main") {
            ContentView(store: store, engine: engine, models: models, identity: identity, inference: inference)
                .frame(minWidth: 980, minHeight: 660)
                .onAppear { delegate.engine = engine; delegate.inference = inference }
        }
        .windowResizability(.contentMinSize)
        .defaultSize(width: 1180, height: 800)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Research") { store.newResearch() }
                    .keyboardShortcut("n", modifiers: .command)
                    .disabled(!store.authenticated)
            }
        }
    }
}
#else
import Foundation
@main
struct DeepdeskUnsupportedPlatform {
    static func main() { print("Deepdesk is a native macOS application. Build on macOS 26.4 or later.") }
}
#endif
