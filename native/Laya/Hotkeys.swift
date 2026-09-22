import AppKit
import Carbon
import Foundation

/// A key combination registered with macOS (the same mechanism Claude and Codex use for ⌥Space).
/// macOS matches the combination itself and only tells us when it is pressed, so no keyboard
/// permission is needed at all.
final class ComboHotkey {
    private var hotKey: EventHotKeyRef?
    private var handler: EventHandlerRef?
    private let action: () -> Void

    init?(keyCode: UInt32, modifiers: UInt32, action: @escaping () -> Void) {
        self.action = action
        var pressed = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let installed = InstallEventHandler(GetApplicationEventTarget(), { _, _, context in
            guard let context else { return noErr }
            let owner = Unmanaged<ComboHotkey>.fromOpaque(context).takeUnretainedValue()
            DispatchQueue.main.async { owner.action() }
            return noErr
        }, 1, &pressed, Unmanaged.passUnretained(self).toOpaque(), &handler)
        guard installed == noErr else { return nil }
        let identifier = EventHotKeyID(signature: OSType(0x4C_42_52_57), id: 1)  // "LBRW"
        guard RegisterEventHotKey(keyCode, modifiers, identifier, GetApplicationEventTarget(), 0, &hotKey) == noErr
        else {
            if let handler { RemoveEventHandler(handler) }
            return nil
        }
    }

    deinit {
        if let hotKey { UnregisterEventHotKey(hotKey) }
        if let handler { RemoveEventHandler(handler) }
    }
}

/// Double-tapping a bare modifier (e.g. Control or Option). AppKit's global monitor for
/// modifier-key changes reports only "a modifier went up or down", never typed characters, and
/// macOS delivers it without Input Monitoring or Accessibility (verified with an app holding
/// neither permission). A local monitor covers the moments LayaBrowse's own menu has focus.
final class ModifierDoubleTap {
    private var monitors: [Any] = []
    private let keycode: UInt16
    private let flag: NSEvent.ModifierFlags
    private let interval: () -> TimeInterval
    private let action: () -> Void
    private var lastDown: TimeInterval = 0
    private var wasDown = false

    init(keycode: UInt16, flag: NSEvent.ModifierFlags, interval: @escaping () -> TimeInterval,
         action: @escaping () -> Void) {
        self.keycode = keycode
        self.flag = flag
        self.interval = interval
        self.action = action
    }

    func start() {
        guard monitors.isEmpty else { return }
        if let global = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged, handler: { [weak self] in
            self?.handle($0)
        }) {
            monitors.append(global)
        }
        if let local = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged, handler: { [weak self] event in
            self?.handle(event)
            return event
        }) {
            monitors.append(local)
        }
    }

    func stop() {
        monitors.forEach(NSEvent.removeMonitor)
        monitors.removeAll()
    }

    private func handle(_ event: NSEvent) {
        guard event.keyCode == keycode else { return }
        let down = event.modifierFlags.contains(flag)
        defer { wasDown = down }
        guard down && !wasDown else { return }
        let now = ProcessInfo.processInfo.systemUptime
        if now - lastDown <= interval() {
            lastDown = 0
            action()
        } else {
            lastDown = now
        }
    }
}
