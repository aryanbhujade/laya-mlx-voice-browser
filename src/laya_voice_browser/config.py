"""User settings shared with the Laya menu-bar app (which writes them) and this backend (which reads them).

`~/Library/Application Support/laya-voice-browser/config.json`; `LAYA_CONFIG` overrides the path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    hotkey: str = "left_control"
    double_tap_ms: float = 350
    mic_sensitivity: str = "medium"
    browser: str = "auto"
    search_engine: str = "google"
    sounds: bool = True
    island: bool = True


def config_path() -> Path:
    override = os.getenv("LAYA_CONFIG")
    if override:
        return Path(override)
    return Path.home() / "Library" / "Application Support" / "laya-voice-browser" / "config.json"


_cache: tuple[float, Settings] | None = None


def load() -> Settings:
    """Current settings; re-read only when the file changes, and defaults for anything missing or bad."""
    global _cache
    path = config_path()
    try:
        modified = path.stat().st_mtime
    except OSError:
        return Settings()
    if _cache and _cache[0] == modified:
        return _cache[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    defaults = Settings()
    values = {}
    for field in fields(Settings):
        value = raw.get(field.name) if isinstance(raw, dict) else None
        default = getattr(defaults, field.name)
        values[field.name] = value if isinstance(value, type(default)) or (
            isinstance(default, float) and isinstance(value, int)
        ) else default
    settings = Settings(**values)
    _cache = (modified, settings)
    return settings
