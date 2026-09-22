import AppKit
import ApplicationServices
import AVFoundation
import CoreGraphics
import Speech

/// The four macOS permissions Laya needs, how to check them and where to grant them.
enum Permission: CaseIterable {
    case speech, microphone, inputMonitoring, accessibility

    var title: String {
        switch self {
        case .speech: return "Speech Recognition"
        case .microphone: return "Microphone"
        case .inputMonitoring: return "Input Monitoring"
        case .accessibility: return "Accessibility"
        }
    }

    var granted: Bool {
        switch self {
        case .speech: return SFSpeechRecognizer.authorizationStatus() == .authorized
        case .microphone: return AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        case .inputMonitoring: return CGPreflightListenEventAccess()
        case .accessibility: return AXIsProcessTrusted()
        }
    }

    private var settingsAnchor: String {
        switch self {
        case .speech: return "Privacy_SpeechRecognition"
        case .microphone: return "Privacy_Microphone"
        case .inputMonitoring: return "Privacy_ListenEvent"
        case .accessibility: return "Privacy_Accessibility"
        }
    }

    func openSettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(settingsAnchor)")!
        NSWorkspace.shared.open(url)
    }

    /// Show the system prompt. Speech and microphone can be answered in place; for Input
    /// Monitoring and Accessibility macOS only offers to open System Settings, where the user
    /// switches Laya on themselves.
    func request(then next: @escaping () -> Void) {
        switch self {
        case .speech:
            SFSpeechRecognizer.requestAuthorization { _ in DispatchQueue.main.async(execute: next) }
        case .microphone:
            AVCaptureDevice.requestAccess(for: .audio) { _ in DispatchQueue.main.async(execute: next) }
        case .inputMonitoring:
            _ = CGRequestListenEventAccess()
            next()
        case .accessibility:
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(options)
            next()
        }
    }

    static var missing: [Permission] { allCases.filter { !$0.granted } }

    /// Ask for each missing permission in turn, so the prompts do not pile up on top of each other.
    static func requestMissing(_ remaining: [Permission] = Permission.missing, then done: @escaping () -> Void) {
        guard let first = remaining.first else { return done() }
        first.request { requestMissing(Array(remaining.dropFirst()), then: done) }
    }
}
