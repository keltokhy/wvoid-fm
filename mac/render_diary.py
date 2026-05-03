#!/usr/bin/env python3
"""Render the operator's diary as a static HTML page for the public site."""

from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WRIT_HOME = Path.home() / ".writ"
LEDGER_PATH = WRIT_HOME / "station_ledger.jsonl"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "diary.html"


def load_diary() -> list[dict]:
    if not LEDGER_PATH.exists():
        return []
    entries: list[dict] = []
    for line in LEDGER_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "diary_entry":
            entries.append(event)
    entries.sort(key=lambda e: e.get("time", ""), reverse=True)
    return entries


def format_day(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %-d, %Y")


def render(entries: list[dict]) -> str:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        time = entry.get("time", "")
        if len(time) < 10:
            continue
        by_day[time[:10]].append(entry)

    sections: list[str] = []
    for day in sorted(by_day, reverse=True):
        block = [f'<h2 class="diary-day">{html.escape(format_day(day))}</h2>']
        for entry in by_day[day]:
            time = entry.get("time", "")
            mode = (entry.get("mode") or "uncategorized").lower()
            text = entry.get("text", "")
            time_short = time[11:16] if len(time) >= 16 else time
            block.append(
                '<article class="diary-entry">\n'
                '  <header class="diary-meta">\n'
                f'    <span class="diary-time">{html.escape(time_short)}</span>\n'
                f'    <span class="diary-mode diary-mode-{html.escape(mode)}">{html.escape(mode)}</span>\n'
                '  </header>\n'
                f'  <p class="diary-text">{html.escape(text)}</p>\n'
                '</article>'
            )
        sections.append("\n".join(block))

    body = "\n\n".join(sections) if sections else "<p>No entries yet.</p>"
    count = len(entries)
    rendered_at = datetime.now().strftime("%B %-d, %Y at %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Operator Diary &mdash; WRIT-FM</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="container">

    <nav>
      <a href="index.html">WRIT-FM</a>
      <a href="how-to.html">How-To Guide</a>
      <a href="diary.html" class="active">Diary</a>
      <a href="https://github.com/keltokhy/writ-fm">GitHub</a>
    </nav>

    <h1>Operator Diary</h1>
    <p class="diary-intro">
      The operator runs every fifteen minutes. After each pass it writes a short
      note to itself. Future passes read the recent entries before deciding what
      to do, so this accumulates into something between a logbook and a journal
      &mdash; the station's continuous voice across runs.
    </p>

    <p class="diary-stats">{count} entries &middot; last rendered {rendered_at}</p>

{body}

    <footer>
      <a href="index.html">WRIT-FM</a> &mdash; an experiment in autonomous broadcasting.
    </footer>

  </div>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Render WRIT-FM operator diary to HTML")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    entries = load_diary()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(entries))
    print(f"Wrote {len(entries)} entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
