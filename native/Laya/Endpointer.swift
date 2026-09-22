import Foundation

/// Decides when a spoken phrase has ended, from how this person speaks and what they said.
///
/// There is no "end of phrase" setting: the wait is learned. It starts from the gaps between the
/// speaker's words (a running mean and spread), waits longer after a connecting word ("and",
/// "search for"), shorter once the backend says the command is already complete, and becomes more
/// patient whenever the speaker resumes right after a phrase was ended (it cut them off).
/// The backend's "complete"/"incomplete" judgements, delivered to whoever owns the endpointer.
enum EndpointHints {
    static var handler: ((String) -> Void)?
}

final class Endpointer {
    struct Profile: Codable {
        var gapMean: Double = 0.30
        var gapSpread: Double = 0.12
        var patience: Double = 1.0
        var samples: Int = 0
    }

    private(set) var profile: Profile
    private var lastWordAt: TimeInterval?
    private var wordCount = 0
    private var lastWord = ""
    private var semantic = 1.0
    private var endedAt: TimeInterval?
    private var dirty = false

    /// Words after which people usually keep going.
    private static let continuing: Set<String> = [
        "and", "then", "the", "a", "an", "to", "for", "of", "on", "in", "into", "with", "my", "search",
        "click", "type", "open", "go", "find", "select", "press", "scroll", "called", "about", "at",
    ]

    init() {
        if let data = try? Data(contentsOf: Self.url),
           let saved = try? JSONDecoder().decode(Profile.self, from: data) {
            profile = saved
        } else {
            profile = Profile()
        }
    }

    static var url: URL {
        LayaSettings.url.deletingLastPathComponent().appendingPathComponent("speech-profile.json")
    }

    /// Seconds of silence after the last new word that end the phrase.
    var timeout: TimeInterval {
        let pace = profile.gapMean + 2.5 * profile.gapSpread + 0.25
        let trailing = Self.continuing.contains(lastWord) ? 1.7 : 1.0
        return min(2.2, max(0.45, pace * profile.patience * semantic * trailing))
    }

    /// When the current phrase should end, measured from now (for re-arming a timer).
    var remaining: TimeInterval {
        guard let lastWordAt else { return timeout }
        return max(0.05, timeout - (ProcessInfo.processInfo.systemUptime - lastWordAt))
    }

    func beginSegment() {
        lastWordAt = nil
        wordCount = 0
        lastWord = ""
        semantic = 1.0
    }

    /// A partial transcript arrived. Learn from the gap before each new word.
    func observe(_ text: String) {
        let words = text.lowercased().split(whereSeparator: { !$0.isLetter && !$0.isNumber })
        let now = ProcessInfo.processInfo.systemUptime
        if wordCount == 0, let endedAt, now - endedAt < 0.6 {
            // Speech resumed almost immediately after we ended the last phrase: we cut them off.
            profile.patience = min(1.8, profile.patience * 1.08)
            dirty = true
        }
        if words.count > wordCount {
            if let lastWordAt {
                let gap = (now - lastWordAt) / Double(words.count - wordCount)
                if gap < 2.0 { learn(gap: gap) }
            }
            lastWordAt = now
            wordCount = words.count
        }
        lastWord = words.last.map(String.init) ?? ""
        semantic = 1.0  // new words: the backend's last judgement no longer applies
    }

    /// The backend's reading of the phrase so far: "complete", "likely_complete" or "incomplete".
    func hint(_ value: String) {
        switch value {
        case "complete": semantic = 0.55  // a finished command: end promptly
        case "likely_complete": semantic = 0.8  // finished words, but dictated text may continue
        case "incomplete": semantic = 1.5
        default: semantic = 1.0
        }
    }

    func segmentEnded() {
        endedAt = ProcessInfo.processInfo.systemUptime
        // Each phrase that did not get cut off nudges patience back toward snappy.
        profile.patience = max(0.8, profile.patience * 0.99)
        save()
    }

    private func learn(gap: Double) {
        let rate = profile.samples < 20 ? 0.2 : 0.06
        let delta = gap - profile.gapMean
        profile.gapMean += rate * delta
        profile.gapSpread += rate * (abs(delta) - profile.gapSpread)
        profile.samples += 1
        dirty = true
    }

    private func save() {
        guard dirty, let data = try? JSONEncoder().encode(profile) else { return }
        try? FileManager.default.createDirectory(at: Self.url.deletingLastPathComponent(),
                                                 withIntermediateDirectories: true)
        try? data.write(to: Self.url, options: .atomic)
        dirty = false
    }
}
