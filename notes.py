"""Helper for maintaining NOTES.md — a human-readable changelog, newest entry at top."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

NOTES_PATH = Path("NOTES.md")

HEADER = "# Copytrade activity log\n\n_Auto-generated. Newest entry at top._\n"


def append_entry(title: str, lines: list[str]) -> None:
    """Prepend a new block under today's `## YYYY-MM-DD` header (create if missing).

    Inside a day, newer entries go above older ones.
    """
    now = datetime.now(timezone.utc)
    day_header = f"## {now.strftime('%Y-%m-%d')}"
    time_header = f"### {now.strftime('%H:%M')} UTC — {title}"
    body = "\n".join(f"- {line}" for line in lines)
    new_block = f"{time_header}\n{body}\n"

    if NOTES_PATH.exists():
        content = NOTES_PATH.read_text()
    else:
        content = HEADER

    if day_header in content:
        # Insert the new block right after the day header (so it's above older entries
        # for the same day), preserving everything else.
        idx = content.index(day_header) + len(day_header)
        # Skip the newline right after the header.
        rest = content[idx:]
        content = content[:idx] + "\n\n" + new_block + rest.lstrip("\n")
    else:
        # New day: insert the day header (with its block) right after the file header.
        if content.endswith("\n\n"):
            prefix = content
        elif content.endswith("\n"):
            prefix = content + "\n"
        else:
            prefix = content + "\n\n"
        content = f"{prefix}{day_header}\n\n{new_block}"

    NOTES_PATH.write_text(content)
