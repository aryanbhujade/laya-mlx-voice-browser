import AVFoundation
import Foundation
import Speech

/// `LayaBrowse --benchmark-speech`: synthesise spoken commands with `say`, transcribe them with the
/// same on-device recogniser LayaBrowse uses, and print timing as JSON lines.
func runSpeechBenchmark() -> Never {
    let phrases = [
        "go to wikipedia", "search for alan turing", "click the talk page",
        "scroll down a little", "open a new tab and go to youtube",
    ]
    let authorized = DispatchSemaphore(value: 0)
    var allowed = false
    SFSpeechRecognizer.requestAuthorization { status in
        allowed = status == .authorized
        authorized.signal()
    }
    authorized.wait()
    guard allowed, let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US")) else {
        print("{\"error\": \"speech recognition not allowed or unavailable\"}")
        exit(1)
    }
    recognizer.queue = OperationQueue()  // callbacks must not need the (blocked) main thread
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent("layabrowse-speech-benchmark")
    try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)

    for (index, phrase) in phrases.enumerated() {
        let audio = folder.appendingPathComponent("\(index).aiff")
        let say = Process()
        say.executableURL = URL(fileURLWithPath: "/usr/bin/say")
        say.arguments = ["-o", audio.path, phrase]
        try? say.run()
        say.waitUntilExit()
        guard let file = try? AVAudioFile(forReading: audio) else { continue }
        let seconds = Double(file.length) / file.processingFormat.sampleRate

        let request = SFSpeechURLRecognitionRequest(url: audio)
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        let done = DispatchSemaphore(value: 0)
        let started = ProcessInfo.processInfo.systemUptime
        var firstPartial: Double?
        var finalAt: Double?
        var text = ""
        let task = recognizer.recognitionTask(with: request) { result, error in
            let now = ProcessInfo.processInfo.systemUptime - started
            if let result {
                if firstPartial == nil { firstPartial = now }
                text = result.bestTranscription.formattedString
                if result.isFinal {
                    finalAt = now
                    done.signal()
                }
            } else if error != nil {
                done.signal()
            }
        }
        _ = done.wait(timeout: .now() + 20)
        task.cancel()
        let line: [String: Any] = [
            "phrase": phrase, "heard": text, "audio_s": round(seconds * 100) / 100,
            "first_partial_ms": Int((firstPartial ?? -1) * 1000), "final_ms": Int((finalAt ?? -1) * 1000),
            "on_device": request.requiresOnDeviceRecognition,
        ]
        if let data = try? JSONSerialization.data(withJSONObject: line, options: [.sortedKeys]) {
            print(String(decoding: data, as: UTF8.self))
            fflush(stdout)
        }
    }
    exit(0)
}
