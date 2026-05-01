#!/usr/bin/env python3
"""
WRIT-FM station ledger.

Append-only editorial memory for events the operator may want to carry forward.
This is intentionally small and file-based so Claude can inspect and curate it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

WRIT_HOME = Path.home() / ".writ"
LEDGER_PATH = WRIT_HOME / "station_ledger.jsonl"
MESSAGES_FILE = WRIT_HOME / "messages.json"
ACTIVE_THREADS_PATH = WRIT_HOME / "active_threads.json"


def utcish_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def event_id(prefix: str, *parts: str) -> str:
    raw = "|".join(p or "" for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def read_events(limit: int | None = None) -> list[dict[str, Any]]:
    if not LEDGER_PATH.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in LEDGER_PATH.read_text().splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events[-limit:] if limit else events


def existing_ids() -> set[str]:
    return {str(e.get("id", "")) for e in read_events()}


def append_event(event: dict[str, Any]) -> bool:
    """Append an event if its id is not already present."""
    if not event.get("id"):
        raise ValueError("ledger event requires id")
    if event["id"] in existing_ids():
        return False
    WRIT_HOME.mkdir(parents=True, exist_ok=True)
    event.setdefault("recorded_at", utcish_now())
    with LEDGER_PATH.open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def classify_message(text: str) -> tuple[str, list[str]]:
    lower = text.lower().strip()
    tags: list[str] = []
    if "?" in text or lower.startswith(("what", "when", "why", "how", "who")):
        tags.append("question")
    if any(place in lower for place in ("socal", "serbia", "detroit", "california")):
        tags.append("listener_geography")
    if len(lower) < 12:
        quality = "low_signal"
    elif tags:
        quality = "substantive"
    else:
        quality = "greeting" if len(lower.split()) <= 5 else "substantive"
    tags.append(quality)
    return quality, tags


def ingest_messages(show_id: str | None = None) -> int:
    """Copy message queue entries into the ledger without mutating the queue."""
    if not MESSAGES_FILE.exists():
        return 0
    try:
        messages = json.loads(MESSAGES_FILE.read_text())
    except Exception:
        return 0

    added = 0
    for msg in messages:
        text = str(msg.get("message", "")).strip()
        ts = str(msg.get("timestamp", "")).strip()
        if not text or not ts:
            continue
        quality, tags = classify_message(text)
        eid = event_id("msg", ts, text)
        expires = datetime.now() + timedelta(days=14 if quality == "substantive" else 3)
        event = {
            "id": eid,
            "type": "listener_message",
            "time": ts,
            "show_id": show_id,
            "text": text,
            "status": "responded" if msg.get("read") else "unread",
            "quality": quality,
            "tags": tags,
            "operator_note": "",
            "expires_at": expires.isoformat(timespec="seconds"),
        }
        added += int(append_event(event))
    return added


def load_active_threads() -> list[dict[str, Any]]:
    if not ACTIVE_THREADS_PATH.exists():
        return []
    try:
        data = json.loads(ACTIVE_THREADS_PATH.read_text())
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return list(data.get("threads", []))
    return []


def save_active_threads(threads: list[dict[str, Any]]) -> None:
    WRIT_HOME.mkdir(parents=True, exist_ok=True)
    ACTIVE_THREADS_PATH.write_text(json.dumps({"threads": threads}, indent=2, ensure_ascii=False))


def add_thread(thread_id: str, title: str, summary: str, shows: list[str], cooldown_hours: int = 48) -> None:
    threads = [t for t in load_active_threads() if t.get("id") != thread_id]
    threads.append({
        "id": thread_id,
        "title": title,
        "summary": summary,
        "shows": shows,
        "status": "active",
        "strength": 0.6,
        "cooldown_hours": cooldown_hours,
        "last_used": None,
        "created_at": utcish_now(),
    })
    save_active_threads(threads)


def add_decision(summary: str, mode: str = "maintenance", show_id: str | None = None, tags: list[str] | None = None) -> bool:
    now = utcish_now()
    return append_event({
        "id": event_id("decision", now, mode, summary),
        "type": "operator_decision",
        "time": now,
        "show_id": show_id,
        "mode": mode,
        "summary": summary,
        "tags": tags or ["operator_decision", mode],
    })


def main() -> int:
    parser = argparse.ArgumentParser(description="WRIT-FM station ledger")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ingest-messages")

    recent = sub.add_parser("recent")
    recent.add_argument("--limit", type=int, default=20)

    thread = sub.add_parser("add-thread")
    thread.add_argument("--id", required=True)
    thread.add_argument("--title", required=True)
    thread.add_argument("--summary", required=True)
    thread.add_argument("--shows", required=True, help="Comma-separated show ids")
    thread.add_argument("--cooldown-hours", type=int, default=48)

    decision = sub.add_parser("add-decision")
    decision.add_argument("--summary", required=True)
    decision.add_argument("--mode", default="maintenance")
    decision.add_argument("--show")
    decision.add_argument("--tags", default="", help="Comma-separated tags")

    args = parser.parse_args()
    if args.cmd == "ingest-messages":
        print(f"ingested={ingest_messages()}")
    elif args.cmd == "recent":
        for event in read_events(args.limit):
            print(json.dumps(event, ensure_ascii=False))
    elif args.cmd == "add-thread":
        shows = [s.strip() for s in args.shows.split(",") if s.strip()]
        add_thread(args.id, args.title, args.summary, shows, args.cooldown_hours)
        print(f"thread={args.id}")
    elif args.cmd == "add-decision":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        added = add_decision(args.summary, mode=args.mode, show_id=args.show, tags=tags or None)
        print(f"decision_added={int(added)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
