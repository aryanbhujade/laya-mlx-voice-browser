import AppKit
import AVFoundation
import Speech

/// The only permissions LayaBrowse needs: to hear you and to turn speech into text. The shortcut
/// needs none (a modifier-change monitor or a registered key combination), and nothing is ever
/// typed or clicked through Accessibility.
enum Permission: CaseIterable {
    case speech, microphone

    var title: String {
        switch self {
        case .speech: return "Speech Recognition"
        case .microphone: return "Microphone"
        }
    }

    var granted: Bool {
        switch self {
        case .speech: return SFSpeechRecognizer.authorizationStatus() == .authorized
        case .microphone: return AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        }
    }

    private var settingsAnchor: String {
        switch self {
        case .speech: return "Privacy_SpeechRecognition"
        case .microphone: return "Privacy_Microphone"
        }
    }

    func openSettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(settingsAnchor)")!
        NSWorkspace.shared.open(url)
    }

    /// Show the system prompt, answered in place.
    func request(then next: @escaping () -> Void) {
        switch self {
        case .speech:
            SFSpeechRecognizer.requestAuthorization { _ in DispatchQueue.main.async(execute: next) }
        case .microphone:
            AVCaptureDevice.requestAccess(for: .audio) { _ in DispatchQueue.main.async(execute: next) }
        }
    }

    static func required(for settings: LayaSettings) -> [Permission] {
        allCases
    }

    static func missing(for settings: LayaSettings) -> [Permission] {
        required(for: settings).filter { !$0.granted }
    }

    /// Ask for each missing permission in turn, so the prompts do not pile up on top of each other.
    static func requestMissing(_ remaining: [Permission], then done: @escaping () -> Void) {
        guard let first = remaining.first else { return done() }
        first.request { requestMissing(Array(remaining.dropFirst()), then: done) }
    }
}
