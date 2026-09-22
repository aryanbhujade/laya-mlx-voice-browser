import Foundation

struct TranscriptEvent: Encodable {
    let text: String
    let final: Bool
    let utterance_id: String
    let at: Double
}

/// Where transcripts and signals go: stdout when Python launched us (development), the backend's
/// stdin when we launched Python (the installed service).
enum Output {
    static var sink: (String) -> Void = { line in
        print(line)
        fflush(stdout)
    }

    static func transcript(_ event: TranscriptEvent) {
        if let data = try? JSONEncoder().encode(event), let line = String(data: data, encoding: .utf8) {
            sink(line)
        }
    }

    static func signal(_ name: String) {
        sink("{\"event\":\"\(name)\"}")
    }
}

func log(_ message: String) {
    fputs("laya: \(message)\n", stderr)
    fflush(stderr)
}

/// Runs `python -m laya_voice_browser backend` as our child and restarts it if it crashes.
/// Transcripts go to its stdin; its stdout carries status lines for the island; its stderr is
/// our log. Being the parent is what makes macOS attribute everything to "Laya".
final class BackendProcess {
    private let python: String
    private let island: NotchIsland
    private var process: Process?
    private var input: FileHandle?
    private var buffered = Data()
    private var stopping = false
    private var failures = 0
    private var startedAt = Date()

    init(python: String, island: NotchIsland) {
        self.python = python
        self.island = island
    }

    func start() {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = ["-m", "laya_voice_browser", "backend"]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        process.environment = environment
        let stdinPipe = Pipe(), stdoutPipe = Pipe()
        process.standardInput = stdinPipe
        process.standardOutput = stdoutPipe
        process.standardError = FileHandle.standardError
        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            DispatchQueue.main.async { self?.receive(data) }
        }
        process.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async { self?.exited(status: finished.terminationStatus) }
        }
        do {
            try process.run()
        } catch {
            log("could not start the backend with \(python): \(error.localizedDescription)")
            exited(status: -1)
            return
        }
        startedAt = Date()
        self.process = process
        input = stdinPipe.fileHandleForWriting
        log("backend started (pid \(process.processIdentifier))")
    }

    func send(_ line: String) {
        guard let data = (line + "\n").data(using: .utf8) else { return }
        try? input?.write(contentsOf: data)
    }

    func stop() {
        stopping = true
        try? input?.close()
        guard let process, process.isRunning else { return }
        process.terminate()
        let deadline = Date().addingTimeInterval(3)
        while process.isRunning && Date() < deadline { usleep(50_000) }
        if process.isRunning { kill(process.processIdentifier, SIGKILL) }
    }

    /// Status lines from Python, one JSON object per line.
    private func receive(_ data: Data) {
        buffered.append(data)
        while let newline = buffered.firstIndex(of: 0x0A) {
            let line = buffered[buffered.startIndex..<newline]
            buffered.removeSubrange(buffered.startIndex...newline)
            guard let object = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { continue }
            if let hint = object["endpoint"] as? String {
                EndpointHints.handler?(hint)
                continue
            }
            guard let raw = object["state"] as? String, let state = IslandState(rawValue: raw) else { continue }
            island.update(IslandStatus(state: state, kind: object["kind"] as? String,
                                       label: object["label"] as? String),
                          ttl: object["ttl"] as? Double)
        }
    }

    private func exited(status: Int32) {
        process = nil
        input = nil
        guard !stopping else { return }
        failures = Date().timeIntervalSince(startedAt) > 30 ? 1 : failures + 1
        let delay = min(60, pow(2, Double(failures)))
        log("backend exited (status \(status)); restarting in \(Int(delay))s")
        island.update(IslandStatus(state: .error, label: "Restarting"), ttl: 2)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            guard let self, !self.stopping else { return }
            self.start()
        }
    }
}
