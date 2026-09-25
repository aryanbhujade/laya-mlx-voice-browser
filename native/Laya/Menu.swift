import AppKit

/// Laya's compact menu-bar mark: an L with a four-point intelligence spark. The listening state
/// keeps the same identity and turns the small companion dot into a second spark.
private func layaMenuIcon(listening: Bool) -> NSImage {
    let size = NSSize(width: 18, height: 18)
    let image = NSImage(size: size, flipped: false) { _ in
        NSColor.black.setFill()

        NSBezierPath(
            roundedRect: NSRect(x: 3.4, y: 3.1, width: 2.6, height: 11.4),
            xRadius: 1.1,
            yRadius: 1.1
        ).fill()
        NSBezierPath(
            roundedRect: NSRect(x: 3.4, y: 3.1, width: 8.4, height: 2.6),
            xRadius: 1.1,
            yRadius: 1.1
        ).fill()

        func sparkle(center: NSPoint, horizontal: CGFloat, vertical: CGFloat, inner: CGFloat) {
            let path = NSBezierPath()
            path.move(to: NSPoint(x: center.x, y: center.y + vertical))
            path.line(to: NSPoint(x: center.x + inner, y: center.y + inner))
            path.line(to: NSPoint(x: center.x + horizontal, y: center.y))
            path.line(to: NSPoint(x: center.x + inner, y: center.y - inner))
            path.line(to: NSPoint(x: center.x, y: center.y - vertical))
            path.line(to: NSPoint(x: center.x - inner, y: center.y - inner))
            path.line(to: NSPoint(x: center.x - horizontal, y: center.y))
            path.line(to: NSPoint(x: center.x - inner, y: center.y + inner))
            path.close()
            path.fill()
        }

        sparkle(center: NSPoint(x: 13.1, y: 13.1), horizontal: 3.5, vertical: 3.8, inner: 1.05)
        if listening {
            sparkle(center: NSPoint(x: 14.9, y: 7.8), horizontal: 1.45, vertical: 1.6, inner: 0.5)
        } else {
            NSBezierPath(ovalIn: NSRect(x: 14.15, y: 7.05, width: 1.5, height: 1.5)).fill()
        }
        return true
    }
    image.isTemplate = true
    image.accessibilityDescription = listening ? "LayaBrowse, listening" : "LayaBrowse"
    return image
}

/// The menu-bar icon: shows Laya is running, what is missing, and every setting.
/// The menu is rebuilt each time it opens, so it always reflects the saved settings and the
/// current permission state.
final class MenuBarItem: NSObject, NSMenuDelegate {
    private let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private var settings: LayaSettings
    private var listening = false
    private let goalLoop: Bool
    private let onToggle: () -> Void
    private let onChange: (LayaSettings) -> Void
    private let onQuit: () -> Void

    init(settings: LayaSettings, goalLoop: Bool = false, onToggle: @escaping () -> Void,
         onChange: @escaping (LayaSettings) -> Void, onQuit: @escaping () -> Void) {
        self.settings = settings
        self.goalLoop = goalLoop
        self.onToggle = onToggle
        self.onChange = onChange
        self.onQuit = onQuit
        super.init()
        let menu = NSMenu()
        menu.delegate = self
        item.menu = menu
        refreshIcon()
    }

    func setListening(_ value: Bool) {
        DispatchQueue.main.async { [self] in
            listening = value
            refreshIcon()
        }
    }

    private func refreshIcon() {
        let image: NSImage
        if !Permission.missing(for: settings).isEmpty {
            image = NSImage(
                systemSymbolName: "exclamationmark.triangle",
                accessibilityDescription: "LayaBrowse needs permission"
            ) ?? layaMenuIcon(listening: listening)
        } else {
            image = layaMenuIcon(listening: listening)
        }
        image.isTemplate = true
        item.button?.image = image
        item.button?.imagePosition = .imageOnly
        item.button?.toolTip = listening ? "LayaBrowse — Listening" : "LayaBrowse"
    }

    // MARK: building the menu

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        refreshIcon()
        menu.addItem(disabled("LayaBrowse"))
        menu.addItem(disabled(goalLoop ? "Laya goal loop" : "Legacy browsing"))
        menu.addItem(disabled(settings.hotkeyOption.instruction))

        let missing = Permission.missing(for: settings)
        if !missing.isEmpty {
            menu.addItem(.separator())
            menu.addItem(disabled("LayaBrowse needs permission:"))
            for permission in missing {
                menu.addItem(action("⚠︎  Allow \(permission.title)…") {
                    permission.request { permission.openSettings() }
                })
            }
        }

        menu.addItem(.separator())
        menu.addItem(action(listening ? "Stop Listening" : "Start Listening") { [weak self] in self?.onToggle() })
        menu.addItem(.separator())

        let shortcut = submenu("Shortcut")
        for option in hotkeyOptions where option.isDoubleTap {
            shortcut.addItem(choice("Double-tap \(option.title)", selected: settings.hotkey == option.id) {
                $0.hotkey = option.id
            })
        }
        shortcut.addItem(.separator())
        for option in hotkeyOptions where !option.isDoubleTap {
            shortcut.addItem(choice("Press \(option.title)", selected: settings.hotkey == option.id) {
                $0.hotkey = option.id
            })
        }
        shortcut.addItem(.separator())
        shortcut.addItem(disabled("Double-tap speed"))
        for (title, value) in doubleTapChoices {
            shortcut.addItem(choice(title, selected: settings.doubleTapMs == value) { $0.doubleTapMs = value })
        }
        menu.addItem(parent(shortcut))

        let style = submenu("Speaking Style")
        for (title, value) in speakingStyleChoices {
            style.addItem(choice(title, selected: settings.speakingStyle == value) { $0.speakingStyle = value })
        }
        menu.addItem(parent(style))

        let sensitivity = submenu("Microphone Sensitivity")
        for (title, value) in sensitivityChoices {
            sensitivity.addItem(choice(title, selected: settings.micSensitivity == value) { $0.micSensitivity = value })
        }
        menu.addItem(parent(sensitivity))

        let browser = submenu("Browser")
        browser.addItem(choice("Automatic (\(automaticBrowser().title))", selected: settings.browser == "auto") {
            $0.browser = "auto"
        })
        browser.addItem(.separator())
        for option in browserOptions where option.installed {
            browser.addItem(choice(option.title, selected: settings.browser == option.key) { $0.browser = option.key })
        }
        menu.addItem(parent(browser))

        let search = submenu("Search Engine")
        for (title, value) in searchChoices {
            search.addItem(choice(title, selected: settings.searchEngine == value) { $0.searchEngine = value })
        }
        menu.addItem(parent(search))

        menu.addItem(choice("Sounds", selected: settings.sounds) { $0.sounds.toggle() })
        menu.addItem(choice("Show Notch Island", selected: settings.island) { $0.island.toggle() })

        menu.addItem(.separator())
        let logURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/laya-voice-browser/service.log")
        if FileManager.default.fileExists(atPath: logURL.path) {
            menu.addItem(action("Open Log") { NSWorkspace.shared.open(logURL) })
        }
        let quit = action("Quit LayaBrowse") { [weak self] in self?.onQuit() }
        quit.keyEquivalent = "q"
        menu.addItem(quit)
    }

    // MARK: menu item helpers

    private final class Handler {
        let run: () -> Void
        init(_ run: @escaping () -> Void) { self.run = run }
    }

    @objc private func runHandler(_ sender: NSMenuItem) {
        (sender.representedObject as? Handler)?.run()
    }

    private func action(_ title: String, _ run: @escaping () -> Void) -> NSMenuItem {
        let menuItem = NSMenuItem(title: title, action: #selector(runHandler(_:)), keyEquivalent: "")
        menuItem.target = self
        menuItem.representedObject = Handler(run)
        return menuItem
    }

    private func choice(_ title: String, selected: Bool, _ change: @escaping (inout LayaSettings) -> Void) -> NSMenuItem {
        let menuItem = action(title) { [weak self] in
            guard let self else { return }
            change(&self.settings)
            self.onChange(self.settings)
        }
        menuItem.state = selected ? .on : .off
        return menuItem
    }

    private func disabled(_ title: String) -> NSMenuItem {
        let menuItem = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        menuItem.isEnabled = false
        return menuItem
    }

    private func submenu(_ title: String) -> NSMenu {
        NSMenu(title: title)
    }

    private func parent(_ submenu: NSMenu) -> NSMenuItem {
        let menuItem = NSMenuItem(title: submenu.title, action: nil, keyEquivalent: "")
        menuItem.submenu = submenu
        return menuItem
    }
}
