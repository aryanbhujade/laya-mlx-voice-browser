import AppKit
import Foundation
import Speech

// LayaBrowse: the menu-bar app. Installed as a login item it runs the Python backend as its child
// (`--service`); in development the Python process launches it as a helper instead.

signal(SIGPIPE, SIG_IGN)
let application = NSApplication.shared
application.setActivationPolicy(.accessory)

if CommandLine.arguments.contains("--preview") {
    runIslandPreview()
}
if CommandLine.arguments.contains("--benchmark-speech") {
    runSpeechBenchmark()
}

let arguments = CommandLine.arguments
let environment = ProcessInfo.processInfo.environment
let serviceMode = arguments.contains("--service")
var settings = LayaSettings.load()

let localeID = environment["LAYA_SPEECH_LOCALE"] ?? Locale.current.identifier
guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeID)) else {
    log("speech recognition is unavailable for locale \(localeID)")
    exit(1)
}

let island = NotchIsland()
island.enabled = settings.island
let speech = SpeechController(recognizer: recognizer, island: island, settings: settings)
var backend: BackendProcess?
var statusListener: StatusListener?
var parentWatch: Timer?
var terminationSource: DispatchSourceSignal?

if serviceMode {
    guard let python = environment["LAYA_PYTHON"] else {
        log("LAYA_PYTHON is not set; reinstall with `layabrowse install`")
        exit(1)
    }
    let process = BackendProcess(python: python, island: island)
    backend = process
    Output.sink = { line in process.send(line) }
    process.start()
    let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
    signal(SIGTERM, SIG_IGN)
    terminate.setEventHandler {
        process.stop()
        exit(0)
    }
    terminate.resume()
    terminationSource = terminate
} else {
    // Development: the Python process started us through LaunchServices and listens on stdout.
    if let raw = environment["LAYA_STATUS_PORT"], let port = UInt16(raw) {
        statusListener = StatusListener(port: port, island: island)
    }
    if let raw = environment["LAYA_PARENT_PID"], let parent = pid_t(raw) {
        let watch = Timer(timeInterval: 2, repeats: true) { _ in
            if kill(parent, 0) != 0 && errno == ESRCH { exit(0) }
        }
        RunLoop.main.add(watch, forMode: .common)
        parentWatch = watch
    }
}

let menuBar = MenuBarItem(
    settings: settings,
    onToggle: { speech.toggleListening() },
    onChange: { updated in
        settings = updated
        updated.save()
        speech.apply(updated)
        Output.signal("config_changed")
    },
    onQuit: {
        if let backend {
            backend.stop()
        } else {
            // The development runner reads this and exits instead of restarting us.
            fputs("laya-speech: quit requested\n", stderr)
            fflush(stderr)
        }
        exit(0)
    }
)
speech.menuBar = menuBar
EndpointHints.handler = { hint in speech.endpointHint(hint) }

// First run: ask for microphone and speech recognition, one prompt at a time. The shortcut needs no
// permission, so it is armed straight away.
speech.startHotkey()
Permission.requestMissing(Permission.missing(for: settings)) {}

fputs("laya-speech: ready pid=\(ProcessInfo.processInfo.processIdentifier)\n", stderr)
fflush(stderr)
application.run()
