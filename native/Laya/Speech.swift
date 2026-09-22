import AppKit
import AVFoundation
import CoreGraphics
import Foundation
import Speech

/// Silences microphone buffers below the sensitivity threshold, keeping the gate open briefly
/// after speech so word endings are not clipped. Runs on the audio thread only.
final class NoiseGate {
    private let threshold: Float
    private var lastLoud: TimeInterval = 0

    init(threshold: Float) { self.threshold = threshold }

    func process(_ buffer: AVAudioPCMBuffer, decibels: Float) {
        let now = ProcessInfo.processInfo.systemUptime
        if decibels >= threshold {
            lastLoud = now
            return
        }
        guard now - lastLoud > 0.35, let channels = buffer.floatChannelData else { return }
        for channel in 0..<Int(buffer.format.channelCount) {
            memset(channels[channel], 0, Int(buffer.frameLength) * MemoryLayout<Float>.size)
        }
    }
}

final class SpeechController {
    private let recognizer: SFSpeechRecognizer
    private let engine = AVAudioEngine()
    private let island: NotchIsland
    weak var menuBar: MenuBarItem?
    private var settings: LayaSettings
    private let endpointer = Endpointer()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var silenceTimer: Timer?
    private var combo: ComboHotkey?
    private var doubleTap: ModifierDoubleTap?
    private var voiceControlActive = false
    private var segmentActive = false
    private var segmentFinalizing = false
    private var lastTranscript = ""
    private var finalEmittedForSegment = false
    private var tapInstalled = false
    private var utteranceID = UUID().uuidString

    init(recognizer: SFSpeechRecognizer, island: NotchIsland, settings: LayaSettings) {
        self.recognizer = recognizer
        self.island = island
        self.settings = settings
    }

    func apply(_ newSettings: LayaSettings) {
        let shortcutChanged = newSettings.hotkey != settings.hotkey
        settings = newSettings
        island.enabled = newSettings.island
        if shortcutChanged { startHotkey() }
    }

    // MARK: hotkey

    /// Arm the chosen shortcut. Neither kind needs a keyboard permission.
    func startHotkey() {
        stopHotkey()
        let option = settings.hotkeyOption
        switch option.kind {
        case .combination(let keyCode, let modifiers):
            combo = ComboHotkey(keyCode: keyCode, modifiers: modifiers) { [weak self] in self?.toggleListening() }
            if combo == nil {
                log("could not register \(option.title); another app may already use it")
                island.update(IslandStatus(state: .error, label: "Shortcut in use"), ttl: 3)
            }
        case .doubleTap(let keycode, let flag):
            let tap = ModifierDoubleTap(keycode: keycode, flag: flag,
                                        interval: { [weak self] in (self?.settings.doubleTapMs ?? 350) / 1000 },
                                        action: { [weak self] in self?.toggleListening() })
            tap.start()
            doubleTap = tap
        }
        log("shortcut ready: \(option.instruction.lowercased())")
    }

    private func stopHotkey() {
        doubleTap?.stop()
        doubleTap = nil
        combo = nil
    }

    // MARK: voice control

    func toggleListening() {
        log("shortcut pressed")
        if voiceControlActive {
            stopVoiceControl()
        } else {
            startVoiceControl()
        }
    }

    private func startVoiceControl() {
        guard !voiceControlActive else { return }
        guard Permission.microphone.granted, Permission.speech.granted else {
            island.update(IslandStatus(state: .error, label: "Allow microphone"), ttl: 3)
            let needed = [Permission.speech, .microphone].filter { !$0.granted }
            Permission.requestMissing(needed) { needed.first(where: { !$0.granted })?.openSettings() }
            return
        }
        voiceControlActive = true
        island.show()
        menuBar?.setListening(true)
        Output.signal("voice_on")
        log("voice control on")
        if settings.sounds { Chime.playStart() }
        startSegment()
    }

    private func stopVoiceControl() {
        guard voiceControlActive else { return }
        voiceControlActive = false
        silenceTimer?.invalidate()
        silenceTimer = nil
        island.hide()
        menuBar?.setListening(false)
        if segmentActive {
            finishSegment()
        } else if !segmentFinalizing {
            cleanupSegment(cancelTask: true)
        }
        log("voice control off")
        if settings.sounds { Chime.playStop() }
    }

    private func startSegment() {
        guard voiceControlActive, !segmentActive, !segmentFinalizing else { return }
        utteranceID = UUID().uuidString
        let segmentID = utteranceID
        lastTranscript = ""
        finalEmittedForSegment = false
        endpointer.beginSegment()
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.contextualStrings = [
            "Laya", "LayaBrowse", "GitHub", "GitHub.com", "YouTube", "Wikipedia", "DuckDuckGo", "Safari", "Chrome",
        ]
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        self.request = request

        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        removeTapIfNeeded()
        let island = self.island
        let gate = NoiseGate(threshold: settings.noiseGateDecibels)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
            let decibels = audioDecibels(buffer)
            gate.process(buffer, decibels: decibels)
            request.append(buffer)
            island.setLevel(displayLevel(decibels: decibels))
        }
        tapInstalled = true

        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            guard segmentID == self.utteranceID else { return }
            if let result {
                let text = result.bestTranscription.formattedString
                if !text.isEmpty {
                    self.lastTranscript = text
                    if result.isFinal { self.finalEmittedForSegment = true }
                    Output.transcript(TranscriptEvent(text: text, final: result.isFinal,
                                                      utterance_id: segmentID,
                                                      at: Date().timeIntervalSince1970))
                    if !result.isFinal {
                        DispatchQueue.main.async {
                            self.endpointer.observe(text)
                            self.resetSilenceTimer()
                        }
                    }
                }
                if result.isFinal {
                    DispatchQueue.main.async { [weak self] in
                        self?.completeSegment(segmentID: segmentID, cancelTask: false)
                    }
                }
            }
            if let error {
                log("recognition: \(error.localizedDescription)")
                DispatchQueue.main.async { [weak self] in
                    self?.completeSegment(segmentID: segmentID, cancelTask: true)
                }
            }
        }

        do {
            engine.prepare()
            try engine.start()
            segmentActive = true
        } catch {
            cleanupSegment(cancelTask: true)
            voiceControlActive = false
            island.hide()
            menuBar?.setListening(false)
            log("could not start microphone: \(error.localizedDescription)")
        }
    }

    /// The backend says the phrase so far is (in)complete: end sooner, or wait longer.
    func endpointHint(_ value: String) {
        endpointer.hint(value)
        resetSilenceTimer()
    }

    private func resetSilenceTimer() {
        DispatchQueue.main.async { [weak self] in
            guard let self, self.voiceControlActive, self.segmentActive else { return }
            self.silenceTimer?.invalidate()
            self.silenceTimer = Timer.scheduledTimer(withTimeInterval: self.endpointer.remaining,
                                                     repeats: false) { [weak self] _ in
                self?.finishSegment()
            }
        }
    }

    private func finishSegment() {
        guard segmentActive else { return }
        let segmentID = utteranceID
        segmentActive = false
        segmentFinalizing = true
        silenceTimer?.invalidate()
        silenceTimer = nil
        request?.endAudio()
        engine.stop()
        removeTapIfNeeded()
        endpointer.segmentEnded()

        // Speech normally emits a final result after endAudio(). Keep a bounded fallback so a
        // recognizer that only supplied partials cannot strand continuous voice control.
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            guard let self, self.segmentFinalizing, self.utteranceID == segmentID else { return }
            if !self.finalEmittedForSegment && !self.lastTranscript.isEmpty {
                Output.transcript(TranscriptEvent(text: self.lastTranscript, final: true,
                                                  utterance_id: segmentID,
                                                  at: Date().timeIntervalSince1970))
                self.finalEmittedForSegment = true
            }
            self.completeSegment(segmentID: segmentID, cancelTask: true)
        }
    }

    private func completeSegment(segmentID: String, cancelTask: Bool) {
        guard utteranceID == segmentID else { return }
        cleanupSegment(cancelTask: cancelTask)
        if voiceControlActive {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.08) { [weak self] in
                self?.startSegment()
            }
        }
    }

    private func cleanupSegment(cancelTask: Bool) {
        if engine.isRunning { engine.stop() }
        removeTapIfNeeded()
        if cancelTask { task?.cancel() }
        task = nil
        request = nil
        segmentActive = false
        segmentFinalizing = false
        silenceTimer?.invalidate()
        silenceTimer = nil
    }

    private func removeTapIfNeeded() {
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
    }
}
