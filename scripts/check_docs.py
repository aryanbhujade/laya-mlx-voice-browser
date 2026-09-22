#!/usr/bin/env python3
"""Fail when a relative Markdown link points to a missing repository file."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^]]*]\(([^)\s]+)(?:\s+[^)]*)?\)")


def main() -> int:
    errors: list[str] = []
    markdown = sorted(path for path in ROOT.rglob("*.md") if ".venv" not in path.parts)
    for document in markdown:
        text = document.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative = unquote(target.split("#", 1)[0])
            if relative and not (document.parent / relative).resolve().exists():
                errors.append(f"{document.relative_to(ROOT)}: missing link target {target}")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"documentation links: {len(markdown)} files checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
