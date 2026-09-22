import AppKit
import Foundation

let serviceLabel = "dev.aryan.layabrowse"

@discardableResult
private func launchctl(_ arguments: [String]) -> Int32 {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
    process.arguments = arguments
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    try? process.run()
    process.waitUntilExit()
    return process.terminationStatus
}

/// Start (or keep) the login-item copy of LayaBrowse, then quit this one. If LayaBrowse was never
/// installed, say how to set it up instead of running without a backend.
func startInstalledService() -> Never {
    let plist = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/LaunchAgents/\(serviceLabel).plist")
    guard FileManager.default.fileExists(atPath: plist.path) else {
        NSApp.activate(ignoringOtherApps: true)
        let alert = NSAlert()
        alert.messageText = "LayaBrowse isn’t set up yet"
        alert.informativeText = "In Terminal, from the LayaBrowse folder, run:\n\nlayabrowse install"
        alert.runModal()
        exit(0)
    }
    let domain = "gui/\(getuid())"
    if launchctl(["print", "\(domain)/\(serviceLabel)"]) != 0 {
        launchctl(["bootstrap", domain, plist.path])  // loaded again after "Quit LayaBrowse"
    }
    launchctl(["kickstart", "\(domain)/\(serviceLabel)"])  // no-op when it is already running
    exit(0)
}
