import AppKit
import CoreGraphics
import Foundation

/// User settings, stored as JSON the Python backend also reads (`laya_voice_browser/config.py`).
struct LayaSettings: Codable, Equatable {
    var hotkey = "left_control"
    var doubleTapMs: Double = 350
    var micSensitivity = "medium"
    var browser = "auto"
    var searchEngine = "google"
    var sounds = true
    var island = true

    enum CodingKeys: String, CodingKey {
        case hotkey, browser, sounds, island
        case doubleTapMs = "double_tap_ms"
        case micSensitivity = "mic_sensitivity"
        case searchEngine = "search_engine"
    }

    init() {}

    /// Missing or unreadable keys fall back to defaults, so old files keep working.
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let defaults = LayaSettings()
        hotkey = (try? values.decode(String.self, forKey: .hotkey)) ?? defaults.hotkey
        doubleTapMs = (try? values.decode(Double.self, forKey: .doubleTapMs)) ?? defaults.doubleTapMs
        micSensitivity = (try? values.decode(String.self, forKey: .micSensitivity)) ?? defaults.micSensitivity
        browser = (try? values.decode(String.self, forKey: .browser)) ?? defaults.browser
        searchEngine = (try? values.decode(String.self, forKey: .searchEngine)) ?? defaults.searchEngine
        sounds = (try? values.decode(Bool.self, forKey: .sounds)) ?? defaults.sounds
        island = (try? values.decode(Bool.self, forKey: .island)) ?? defaults.island
    }

    static var url: URL {
        if let override = ProcessInfo.processInfo.environment["LAYA_CONFIG"] {
            return URL(fileURLWithPath: override)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/laya-voice-browser/config.json")
    }

    static func load() -> LayaSettings {
        guard let data = try? Data(contentsOf: url),
              let settings = try? JSONDecoder().decode(LayaSettings.self, from: data) else { return LayaSettings() }
        return settings
    }

    func save() {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? encoder.encode(self) else { return }
        try? FileManager.default.createDirectory(at: Self.url.deletingLastPathComponent(),
                                                 withIntermediateDirectories: true)
        try? data.write(to: Self.url, options: .atomic)
    }

    var hotkeyOption: HotkeyOption {
        hotkeyOptions.first(where: { $0.id == hotkey }) ?? hotkeyOptions[0]
    }

    /// Microphone buffers quieter than this are silenced before recognition (a noise gate).
    var noiseGateDecibels: Float {
        switch micSensitivity {
        case "low": return -38
        case "high": return -70
        default: return -50
        }
    }
}

struct HotkeyOption {
    let id: String
    let title: String
    let keycode: Int64
    let flag: CGEventFlags
}

/// A modifier key tapped twice. Right-hand keys avoid clashing with everyday shortcuts.
let hotkeyOptions = [
    HotkeyOption(id: "left_control", title: "Left Control ⌃", keycode: 59, flag: .maskControl),
    HotkeyOption(id: "right_control", title: "Right Control ⌃", keycode: 62, flag: .maskControl),
    HotkeyOption(id: "right_option", title: "Right Option ⌥", keycode: 61, flag: .maskAlternate),
    HotkeyOption(id: "right_command", title: "Right Command ⌘", keycode: 54, flag: .maskCommand),
]

let doubleTapChoices: [(String, Double)] = [("Fast", 250), ("Normal", 350), ("Relaxed", 500)]
let sensitivityChoices: [(String, String)] = [
    ("Low — ignore background noise", "low"),
    ("Medium", "medium"),
    ("High — pick up quiet speech", "high"),
]
let searchChoices: [(String, String)] = [("Google", "google"), ("DuckDuckGo", "duckduckgo")]

struct BrowserOption {
    let key: String
    let title: String
    let bundleID: String

    var installed: Bool {
        NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleID) != nil
    }
}

/// Same keys as `laya_voice_browser/chromium.py`, plus Safari.
let browserOptions = [
    BrowserOption(key: "safari", title: "Safari", bundleID: "com.apple.Safari"),
    BrowserOption(key: "chrome", title: "Google Chrome", bundleID: "com.google.Chrome"),
    BrowserOption(key: "edge", title: "Microsoft Edge", bundleID: "com.microsoft.edgemac"),
    BrowserOption(key: "brave", title: "Brave", bundleID: "com.brave.Browser"),
    BrowserOption(key: "chromium", title: "Chromium", bundleID: "org.chromium.Chromium"),
    BrowserOption(key: "vivaldi", title: "Vivaldi", bundleID: "com.vivaldi.Vivaldi"),
    BrowserOption(key: "opera", title: "Opera", bundleID: "com.operasoftware.Opera"),
    BrowserOption(key: "opera_gx", title: "Opera GX", bundleID: "com.operasoftware.OperaGX"),
]

/// What "Automatic" will use: the default browser if Laya can drive it, otherwise Safari.
func automaticBrowser() -> BrowserOption {
    let probe = URL(string: "https://example.com")!
    if let app = NSWorkspace.shared.urlForApplication(toOpen: probe),
       let bundle = Bundle(url: app)?.bundleIdentifier?.lowercased(),
       let match = browserOptions.first(where: { $0.bundleID.lowercased() == bundle }) {
        return match
    }
    return browserOptions[0]
}
