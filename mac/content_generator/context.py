#!/usr/bin/env python3
"""
Operator brief and prompt context for WRIT-FM.

This module centralizes the station's dynamic memory so generators do not each
invent their own view of listener messages, recent topics, and operator intent.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ledger import ingest_messages, load_active_threads, read_events

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.yaml"
OUTPUT_DIR = PROJECT_ROOT / "output" / "talk_segments"
SHOW_LOG_DIR = PROJECT_ROOT / "output" / "show_logs"
INTENT_DIR = PROJECT_ROOT / "output" / "operator_intents"

import sys
sys.path.insert(0, str(PROJECT_ROOT / "mac"))
from schedule import load_schedule, slot_key  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def slot_count(show_id: str, slot: str) -> int:
    slot_dir = OUTPUT_DIR / show_id / slot
    if not slot_dir.exists():
        return 0
    return len(list(slot_dir.glob("*.wav")))


def recent_show_entries(show_id: str, limit: int = 6) -> list[dict[str, Any]]:
    path = SHOW_LOG_DIR / f"{show_id}.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def recent_listener_events(limit: int = 8) -> list[dict[str, Any]]:
    events = [
        e for e in read_events()
        if e.get("type") == "listener_message" and e.get("quality") != "low_signal"
    ]
    return events[-limit:]


def relevant_threads(show_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    threads = [t for t in load_active_threads() if t.get("status", "active") == "active"]
    if show_id:
        threads = [
            t for t in threads
            if not t.get("shows") or show_id in t.get("shows", []) or "all" in t.get("shows", [])
        ]
    return threads[:limit]


def build_operator_brief(min_segments: int = 6) -> dict[str, Any]:
    ingest_messages()
    schedule = load_schedule(SCHEDULE_PATH)
    resolved = schedule.resolve()
    current_slot = slot_key(schedule.airing_start())
    airings = []
    for show_id, airing_start in schedule.next_airings(count=8):
        slot = slot_key(airing_start)
        show = schedule.shows[show_id]
        count = slot_count(show_id, slot)
        airings.append({
            "show_id": show_id,
            "show_name": show.name,
            "slot": slot,
            "segments": count,
            "status": "ok" if count >= min_segments else "low" if count >= 3 else "empty",
        })

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "current_show": {
            "show_id": resolved.show_id,
            "show_name": resolved.name,
            "host": resolved.host,
            "topic_focus": resolved.topic_focus,
            "slot": current_slot,
            "segments": slot_count(resolved.show_id, current_slot),
        },
        "upcoming_airings": airings,
        "active_threads": relevant_threads(resolved.show_id),
        "recent_listener_events": recent_listener_events(),
        "recent_show_memory": recent_show_entries(resolved.show_id),
    }


def format_operator_brief(brief: dict[str, Any]) -> str:
    current = brief["current_show"]
    lines = [
        "=== WRIT-FM Operator Brief ===",
        f"Generated: {brief['generated_at']}",
        "",
        f"Current: {current['show_name']} ({current['show_id']})",
        f"Host: {current['host']} | Focus: {current['topic_focus']}",
        f"Slot: {current['slot']} | Segments: {current['segments']}",
        "",
        "Upcoming slots:",
    ]
    for airing in brief["upcoming_airings"]:
        lines.append(
            f"- {airing['slot']} {airing['show_name']}: "
            f"{airing['segments']} segments [{airing['status']}]"
        )

    if brief["active_threads"]:
        lines.extend(["", "Active editorial threads:"])
        for thread in brief["active_threads"]:
            lines.append(f"- {thread.get('id')}: {thread.get('summary')}")

    if brief["recent_listener_events"]:
        lines.extend(["", "Recent listener material:"])
        for event in brief["recent_listener_events"][-5:]:
            lines.append(f"- [{event.get('status')}] {event.get('text')}")

    if brief["recent_show_memory"]:
        lines.extend(["", "Recent show memory:"])
        for entry in brief["recent_show_memory"][-5:]:
            lines.append(f"- {entry.get('type')}: {entry.get('topic')}")

    lines.extend([
        "",
        "Intent card shape:",
        json.dumps({
            "mode": "maintenance|responsive|continuity|special|quiet",
            "intent": "one sentence editorial intent",
            "show_id": current["show_id"],
            "segment_type": "deep_dive",
            "topic": "optional specific topic",
            "tone": "optional tone note",
            "use_threads": [],
            "avoid": [],
        }, indent=2),
    ])
    return "\n".join(lines)


def load_intent(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return read_json(Path(path))


def format_prompt_context(intent: dict[str, Any], show_id: str | None = None) -> str:
    """Convert an operator intent card into a compact prompt block."""
    if not intent:
        return ""

    parts = ["OPERATOR INTENT (editorial direction for this segment):"]
    for key in ("mode", "intent", "tone"):
        if intent.get(key):
            parts.append(f"- {key}: {intent[key]}")

    use_thread_ids = set(intent.get("use_threads") or [])
    threads = relevant_threads(show_id)
    if use_thread_ids:
        threads = [t for t in threads if t.get("id") in use_thread_ids]
    if threads:
        parts.append("Active threads to use lightly:")
        for thread in threads:
            parts.append(f"- {thread.get('title', thread.get('id'))}: {thread.get('summary')}")

    if intent.get("avoid"):
        parts.append("Avoid repeating or leaning on:")
        for item in intent["avoid"]:
            parts.append(f"- {item}")

    if intent.get("listener_material"):
        parts.append("Listener material selected by operator:")
        for item in intent["listener_material"]:
            parts.append(f"- {item}")

    return "\n".join(parts)


def write_intent_template(path: Path | None = None) -> Path:
    brief = build_operator_brief()
    current = brief["current_show"]
    path = path or INTENT_DIR / f"intent_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    template = {
        "mode": "maintenance",
        "intent": "Keep the current and upcoming station flow stocked without forcing listener callbacks.",
        "show_id": current["show_id"],
        "segment_type": None,
        "topic": None,
        "tone": "",
        "use_threads": [],
        "avoid": [],
        "listener_material": [],
    }
    path.write_text(json.dumps(template, indent=2))
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="WRIT-FM operator context")
    parser.add_argument("--operator-brief", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-intent-template", nargs="?", const="", metavar="PATH")
    args = parser.parse_args()

    if args.write_intent_template is not None:
        path = Path(args.write_intent_template) if args.write_intent_template else None
        print(write_intent_template(path))
        return 0

    brief = build_operator_brief()
    if args.json:
        print(json.dumps(brief, indent=2, ensure_ascii=False))
    else:
        print(format_operator_brief(brief))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
