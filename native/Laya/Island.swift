import AppKit
import AVFoundation
import Foundation
import Network
import QuartzCore

// MARK: - Notch island

/// What the island shows on its left wing. Python sends these over localhost UDP.
enum IslandState: String {
    case listening, thinking, acting, done, confirm, choose, unsure, error
}

struct IslandStatus {
    var state: IslandState
    var kind: String? = nil
    var label: String? = nil
}

/// The notch rectangle in screen coordinates, or a notch-sized pill on Macs without one.
struct NotchGeometry {
    let screenFrame: NSRect
    let notchMinX: CGFloat
    let notchMaxX: CGFloat
    let height: CGFloat

    static func current() -> NotchGeometry {
        let screens = NSScreen.screens
        let screen = screens.first(where: { $0.safeAreaInsets.top > 0 }) ?? NSScreen.main ?? screens[0]
        let frame = screen.frame
        let top = screen.safeAreaInsets.top
        if top > 0, let left = screen.auxiliaryTopLeftArea, let right = screen.auxiliaryTopRightArea {
            // The auxiliary areas run from each screen edge to the notch, so their widths locate it.
            return NotchGeometry(screenFrame: frame, notchMinX: frame.minX + left.width,
                                 notchMaxX: frame.maxX - right.width, height: top)
        }
        let menuBar = max(24, frame.maxY - screen.visibleFrame.maxY)
        return NotchGeometry(screenFrame: frame, notchMinX: frame.midX - 60,
                             notchMaxX: frame.midX + 60, height: menuBar)
    }
}

final class IslandView: NSView {
    static let wing: CGFloat = 138
    static let shoulder: CGFloat = 6

    private let shape = CAShapeLayer()
    // A faint rim plus a soft glint that travels along it; both skip the top edge (the screen edge).
    private let rim = CALayer()
    private let border = CAShapeLayer()
    private let glint = CAGradientLayer()
    private let glintMask = CAShapeLayer()
    private let content = CALayer()
    private let icon = CALayer()
    private let label = CATextLayer()
    private var bars: [CALayer] = []
    private let notchWidth: CGFloat
    private var status = IslandStatus(state: .listening)
    private var level: CGFloat = 0
    private var targetLevel: CGFloat = 0
    private var phase: CGFloat = 0
    private var frameTimer: Timer?

    init(frame: NSRect, notchWidth: CGFloat) {
        self.notchWidth = notchWidth
        super.init(frame: frame)
        wantsLayer = true
        layer?.masksToBounds = false
        shape.fillColor = NSColor.black.cgColor
        shape.path = islandPath(extra: -Self.shoulder)
        shape.opacity = 0
        layer?.addSublayer(shape)

        rim.frame = bounds
        rim.opacity = 0
        border.frame = bounds
        border.path = islandPath(extra: -Self.shoulder, closed: false)
        border.fillColor = nil
        border.strokeColor = NSColor(calibratedWhite: 1, alpha: 0.08).cgColor
        border.lineWidth = 1
        rim.addSublayer(border)
        glintMask.frame = bounds
        glintMask.path = border.path
        glintMask.fillColor = nil
        glintMask.strokeColor = NSColor.black.cgColor
        glintMask.lineWidth = 1.4
        glint.frame = bounds
        glint.startPoint = CGPoint(x: 0, y: 0.5)
        glint.endPoint = CGPoint(x: 1, y: 0.5)
        let clear = NSColor(calibratedWhite: 1, alpha: 0).cgColor
        glint.colors = [clear, NSColor(calibratedWhite: 1, alpha: 0.55).cgColor, clear]
        glint.locations = [-0.16, -0.08, 0]
        glint.mask = glintMask
        rim.addSublayer(glint)
        layer?.addSublayer(rim)

        content.frame = bounds
        content.opacity = 0
        layer?.addSublayer(content)
        icon.contentsGravity = .resizeAspect
        content.addSublayer(icon)
        label.font = NSFont.systemFont(ofSize: 12, weight: .semibold)
        label.fontSize = 12
        label.truncationMode = .end
        label.foregroundColor = NSColor(calibratedWhite: 0.94, alpha: 1).cgColor
        content.addSublayer(label)
        for _ in 0..<5 {
            let bar = CALayer()
            bar.cornerRadius = 1.5
            bar.backgroundColor = NSColor(calibratedWhite: 0.92, alpha: 1).cgColor
            content.addSublayer(bar)
            bars.append(bar)
        }
        layoutContent()
        apply(status, animated: false)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) is not used") }

    /// Black shape hugging the notch: flat top, concave shoulders, rounded bottom corners.
    /// `extra` widens each side beyond the notch; every width uses the same path elements so the
    /// spring animation can interpolate between them.
    private func islandPath(extra: CGFloat, closed: Bool = true) -> CGPath {
        let height = bounds.height, centre = bounds.width / 2, s = Self.shoulder
        let radius = min(height * 0.34, 12)
        let left = centre - notchWidth / 2 - extra, right = centre + notchWidth / 2 + extra
        let path = CGMutablePath()
        path.move(to: CGPoint(x: left - s, y: height))
        path.addQuadCurve(to: CGPoint(x: left, y: height - s), control: CGPoint(x: left, y: height))
        path.addLine(to: CGPoint(x: left, y: radius))
        path.addQuadCurve(to: CGPoint(x: left + radius, y: 0), control: CGPoint(x: left, y: 0))
        path.addLine(to: CGPoint(x: right - radius, y: 0))
        path.addQuadCurve(to: CGPoint(x: right, y: radius), control: CGPoint(x: right, y: 0))
        path.addLine(to: CGPoint(x: right, y: height - s))
        path.addQuadCurve(to: CGPoint(x: right + s, y: height), control: CGPoint(x: right, y: height))
        if closed { path.closeSubpath() }
        return path
    }

    private func layoutContent() {
        let height = bounds.height, centre = bounds.width / 2
        let wingLeft = centre - notchWidth / 2 - Self.wing
        let iconSize: CGFloat = 15
        icon.frame = NSRect(x: wingLeft + 14, y: (height - iconSize) / 2, width: iconSize, height: iconSize)
        let labelHeight: CGFloat = 16
        label.frame = NSRect(x: wingLeft + 14 + iconSize + 7, y: (height - labelHeight) / 2 - 1,
                             width: Self.wing - 14 - iconSize - 7 - 8, height: labelHeight)
        let barsWidth = CGFloat(bars.count) * 3 + CGFloat(bars.count - 1) * 3.5
        let barsLeft = centre + notchWidth / 2 + (Self.wing - barsWidth) / 2
        for (index, bar) in bars.enumerated() {
            bar.frame = NSRect(x: barsLeft + CGFloat(index) * 6.5, y: height / 2 - 1.5, width: 3, height: 3)
        }
    }

    override func viewDidChangeBackingProperties() {
        super.viewDidChangeBackingProperties()
        let scale = window?.backingScaleFactor ?? 2
        label.contentsScale = scale
        icon.contentsScale = scale
    }

    func expand() {
        animatePaths(extra: Self.wing)
        shape.opacity = 1
        rim.opacity = 1
        startGlint()
        let fade = CABasicAnimation(keyPath: "opacity")
        fade.fromValue = 0
        fade.toValue = 1
        fade.beginTime = CACurrentMediaTime() + 0.12
        fade.duration = 0.22
        fade.fillMode = .backwards
        content.add(fade, forKey: "fadeIn")
        content.opacity = 1
        startFrames()
    }

    func collapse(completion: @escaping () -> Void) {
        CATransaction.begin()
        CATransaction.setAnimationDuration(0.12)
        content.opacity = 0
        rim.opacity = 0
        CATransaction.commit()
        let settle = animatePaths(extra: -Self.shoulder)
        DispatchQueue.main.asyncAfter(deadline: .now() + min(settle, 0.45)) { [weak self] in
            guard let self else { return }
            CATransaction.begin()
            CATransaction.setAnimationDuration(0.08)
            self.shape.opacity = 0
            CATransaction.commit()
            self.stopFrames()
            self.glint.removeAnimation(forKey: "sweep")
            completion()
        }
    }

    /// Spring the fill, rim and glint mask together so the border tracks the growing shape.
    @discardableResult
    private func animatePaths(extra: CGFloat) -> CFTimeInterval {
        let fill = islandPath(extra: extra)
        let edge = islandPath(extra: extra, closed: false)
        var settle: CFTimeInterval = 0
        for (layer, path) in [(shape, fill), (border, edge), (glintMask, edge)] {
            let spring = CASpringAnimation(keyPath: "path")
            spring.fromValue = layer.presentation()?.path ?? layer.path
            spring.toValue = path
            spring.mass = 1
            spring.stiffness = 260
            spring.damping = 24
            spring.duration = spring.settlingDuration
            layer.path = path
            layer.add(spring, forKey: "path")
            settle = spring.settlingDuration
        }
        return settle
    }

    /// A soft highlight sweeps left to right along the rim, then rests before the next pass.
    private func startGlint() {
        guard glint.animation(forKey: "sweep") == nil else { return }
        let sweep = CABasicAnimation(keyPath: "locations")
        sweep.fromValue = [-0.16, -0.08, 0]
        sweep.toValue = [1, 1.08, 1.16]
        sweep.duration = 2.4
        sweep.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        let cycle = CAAnimationGroup()
        cycle.animations = [sweep]
        cycle.duration = 4.2
        cycle.repeatCount = .infinity
        glint.add(cycle, forKey: "sweep")
    }

    func setLevel(_ value: Float) {
        targetLevel = CGFloat(max(0, min(1, value)))
    }

    func apply(_ newStatus: IslandStatus, animated: Bool = true) {
        status = newStatus
        let (symbol, text, tint) = Self.presentation(for: newStatus)
        if animated {
            let fade = CATransition()
            fade.type = .fade
            fade.duration = 0.18
            icon.add(fade, forKey: "swap")
            label.add(fade, forKey: "swap")
        }
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        let configuration = NSImage.SymbolConfiguration(pointSize: 13, weight: .semibold)
            .applying(NSImage.SymbolConfiguration(hierarchicalColor: tint))
        icon.contents = NSImage(systemSymbolName: symbol, accessibilityDescription: text)?
            .withSymbolConfiguration(configuration)
        label.string = text
        for bar in bars {
            bar.backgroundColor = (newStatus.state == .listening ? NSColor(calibratedWhite: 0.92, alpha: 1) : tint)
                .cgColor
        }
        CATransaction.commit()
    }

    private static func presentation(for status: IslandStatus) -> (String, String, NSColor) {
        let white = NSColor(calibratedWhite: 0.92, alpha: 1)
        let blue = NSColor(calibratedRed: 0.35, green: 0.62, blue: 1, alpha: 1)
        let green = NSColor(calibratedRed: 0.30, green: 0.85, blue: 0.45, alpha: 1)
        let orange = NSColor(calibratedRed: 1, green: 0.62, blue: 0.2, alpha: 1)
        let red = NSColor(calibratedRed: 1, green: 0.36, blue: 0.36, alpha: 1)
        let (symbol, text, tint): (String, String, NSColor)
        switch status.state {
        case .listening: (symbol, text, tint) = ("mic.fill", "Listening", white)
        case .thinking: (symbol, text, tint) = ("sparkles", "Thinking", blue)
        case .done: (symbol, text, tint) = ("checkmark.circle.fill", "Done", green)
        case .confirm: (symbol, text, tint) = ("exclamationmark.triangle.fill", "Say confirm", orange)
        case .choose: (symbol, text, tint) = ("number", "Say a number", blue)
        case .unsure: (symbol, text, tint) = ("questionmark.circle.fill", "Didn't get that", orange)
        case .error: (symbol, text, tint) = ("xmark.octagon.fill", "Error", red)
        case .acting:
            switch status.kind ?? "" {
            case "search": (symbol, text, tint) = ("magnifyingglass", "Searching", blue)
            case "navigate": (symbol, text, tint) = ("safari.fill", "Opening", blue)
            case "click": (symbol, text, tint) = ("cursorarrow.click.2", "Clicking", blue)
            case "type", "select": (symbol, text, tint) = ("keyboard.fill", "Typing", blue)
            case "scroll": (symbol, text, tint) = ("arrow.up.and.down", "Scrolling", blue)
            case "back": (symbol, text, tint) = ("chevron.backward.circle.fill", "Going back", blue)
            case "forward": (symbol, text, tint) = ("chevron.forward.circle.fill", "Forward", blue)
            case "reload": (symbol, text, tint) = ("arrow.clockwise", "Reloading", blue)
            case "new_tab", "close_tab", "switch_tab":
                (symbol, text, tint) = ("square.on.square", "Tabs", blue)
            case "press_enter": (symbol, text, tint) = ("return", "Return", blue)
            default: (symbol, text, tint) = ("bolt.fill", "Working", blue)
            }
        }
        return (symbol, status.label ?? text, tint)
    }

    private func startFrames() {
        guard frameTimer == nil else { return }
        let timer = Timer(timeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in self?.tick() }
        RunLoop.main.add(timer, forMode: .common)
        frameTimer = timer
    }

    private func stopFrames() {
        frameTimer?.invalidate()
        frameTimer = nil
    }

    /// Voice-reactive bars while listening; a slow travelling wave while working.
    private func tick() {
        phase += 1.0 / 60.0
        let smoothing: CGFloat = targetLevel > level ? 0.45 : 0.12
        level += (targetLevel - level) * smoothing
        let maxHeight = bounds.height - 16
        let weights: [CGFloat] = [0.55, 0.85, 1.0, 0.8, 0.5]
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        for (index, bar) in bars.enumerated() {
            let wobble = 0.72 + 0.28 * sin(phase * (7 + CGFloat(index) * 1.7) + CGFloat(index))
            let height: CGFloat
            switch status.state {
            case .listening:
                height = 3 + (maxHeight - 3) * level * weights[index] * wobble
            case .thinking, .acting:
                height = 3 + 5 * (0.5 + 0.5 * sin(phase * 5 - CGFloat(index) * 0.8))
            default:
                height = 3
            }
            var frame = bar.frame
            frame.size.height = height
            frame.origin.y = (bounds.height - height) / 2
            bar.frame = frame
        }
        CATransaction.commit()
    }
}

/// A borderless, click-through panel over the notch. It never extends below the notch.
final class NotchIsland {
    /// Off in settings: nothing is drawn, statuses are ignored.
    var enabled = true
    private let panel: NSPanel
    private let view: IslandView
    private var visible = false
    private var pinned = false
    private var revertWork: DispatchWorkItem?
    private var baseStatus = IslandStatus(state: .listening)

    init() {
        let geometry = NotchGeometry.current()
        let notchWidth = geometry.notchMaxX - geometry.notchMinX
        let width = notchWidth + 2 * (IslandView.wing + IslandView.shoulder)
        let frame = NSRect(x: geometry.notchMinX - IslandView.wing - IslandView.shoulder,
                           y: geometry.screenFrame.maxY - geometry.height,
                           width: width, height: geometry.height)
        panel = NSPanel(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel],
                        backing: .buffered, defer: false)
        view = IslandView(frame: NSRect(origin: .zero, size: frame.size), notchWidth: notchWidth)
        panel.contentView = view
        panel.backgroundColor = .clear
        panel.isOpaque = false
        panel.hasShadow = false
        panel.ignoresMouseEvents = true
        panel.hidesOnDeactivate = false
        panel.level = .screenSaver
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle]
        panel.isReleasedWhenClosed = false
    }

    /// Voice control is on: stay open until `hide()`.
    func show() {
        DispatchQueue.main.async { [self] in
            pinned = true
            baseStatus = IslandStatus(state: .listening)
            view.apply(baseStatus)
            open()
        }
    }

    func hide() {
        DispatchQueue.main.async { [self] in
            pinned = false
            revertWork?.cancel()
            close()
        }
    }

    func setLevel(_ level: Float) {
        DispatchQueue.main.async { [self] in view.setLevel(level) }
    }

    /// Show a status; after `ttl` seconds return to listening, or close if voice control is off.
    func update(_ status: IslandStatus, ttl: Double?) {
        DispatchQueue.main.async { [self] in
            revertWork?.cancel()
            view.apply(status)
            if !visible { open() }
            guard let ttl else { return }
            let work = DispatchWorkItem { [weak self] in
                guard let self else { return }
                if self.pinned {
                    self.view.apply(self.baseStatus)
                } else {
                    self.close()
                }
            }
            revertWork = work
            DispatchQueue.main.asyncAfter(deadline: .now() + ttl, execute: work)
        }
    }

    private func open() {
        guard enabled, !visible else { return }
        visible = true
        panel.orderFrontRegardless()
        view.expand()
    }

    private func close() {
        guard visible else { return }
        visible = false
        view.collapse { [weak self] in
            guard let self, !self.visible else { return }
            self.panel.orderOut(nil)
        }
    }
}

/// Receives `{"state": "...", "kind": "...", "label": "...", "ttl": 1.2}` datagrams from Python.
final class StatusListener {
    private let listener: NWListener

    init?(port: UInt16, island: NotchIsland) {
        guard let endpointPort = NWEndpoint.Port(rawValue: port) else { return nil }
        let parameters = NWParameters.udp
        parameters.requiredLocalEndpoint = NWEndpoint.hostPort(host: "127.0.0.1", port: endpointPort)
        guard let listener = try? NWListener(using: parameters) else { return nil }
        self.listener = listener
        listener.newConnectionHandler = { connection in
            connection.start(queue: .main)
            func receive() {
                connection.receiveMessage { data, _, _, error in
                    if let data,
                       let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let hint = object["endpoint"] as? String {
                        DispatchQueue.main.async { EndpointHints.handler?(hint) }
                    } else if let data,
                       let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                       let raw = object["state"] as? String,
                       let state = IslandState(rawValue: raw) {
                        let status = IslandStatus(state: state, kind: object["kind"] as? String,
                                                  label: object["label"] as? String)
                        island.update(status, ttl: object["ttl"] as? Double)
                    }
                    if error == nil { receive() }
                }
            }
            receive()
        }
        listener.start(queue: .main)
    }
}

/// Loudness of one microphone buffer in dBFS (about -100 for silence, 0 for full scale).
func audioDecibels(_ buffer: AVAudioPCMBuffer) -> Float {
    guard let samples = buffer.floatChannelData?[0], buffer.frameLength > 0 else { return -100 }
    let count = Int(buffer.frameLength)
    var sum: Float = 0
    for index in 0..<count { sum += samples[index] * samples[index] }
    return 20 * log10(max(sqrt(sum / Float(count)), 1e-7))
}

/// Loudness mapped to 0...1 for the waveform bars.
func displayLevel(decibels: Float) -> Float {
    min(1, max(0, (decibels + 55) / 40))
}

/// `Laya --preview`: cycle the island through every state with a synthetic voice, no
/// permissions needed. Useful for design work.
func runIslandPreview() -> Never {
    let island = NotchIsland()
    island.show()
    // With LAYA_STATUS_PORT set, show statuses sent by Python instead of the scripted demo.
    if let raw = ProcessInfo.processInfo.environment["LAYA_STATUS_PORT"], let port = UInt16(raw) {
        let listener = StatusListener(port: port, island: island)
        withExtendedLifetime(listener) { NSApp.run() }
        exit(0)
    }
    var time: Double = 0
    let voice = Timer(timeInterval: 1.0 / 30.0, repeats: true) { _ in
        time += 1.0 / 30.0
        let syllables = max(0, sin(time * 9) * sin(time * 2.3 + 1))
        island.setLevel(time < 4.5 ? Float(0.25 + 0.7 * syllables) : 0.05)
    }
    RunLoop.main.add(voice, forMode: .common)
    let script: [(Double, IslandStatus, Double?)] = [
        (4.5, IslandStatus(state: .thinking), nil),
        (5.5, IslandStatus(state: .acting, kind: "search"), nil),
        (6.8, IslandStatus(state: .done), 1.2),
        (8.4, IslandStatus(state: .choose), nil),
        (10.0, IslandStatus(state: .confirm), nil),
        (11.6, IslandStatus(state: .unsure), 1.4),
    ]
    for (at, status, ttl) in script {
        DispatchQueue.main.asyncAfter(deadline: .now() + at) { island.update(status, ttl: ttl) }
    }
    let seconds = Double(ProcessInfo.processInfo.environment["LAYA_PREVIEW_SECONDS"] ?? "") ?? 14
    DispatchQueue.main.asyncAfter(deadline: .now() + seconds) { island.hide() }
    DispatchQueue.main.asyncAfter(deadline: .now() + seconds + 0.8) { exit(0) }
    NSApp.run()
    exit(0)
}
