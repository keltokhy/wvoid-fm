#!/usr/bin/env python3
"""
WRIT-FM Listener Response Generator

Watches for new listener messages and generates short, personalized on-air responses.
Designed to run as a daemon for near-real-time message incorporation.

Flow:
  1. Read ~/.writ/messages.json for unread messages
  2. Batch 1-3 messages into a short response segment (~200-400 words)
  3. Generate script via Claude CLI
  4. Render audio via Kokoro TTS
  5. Drop into output/talk_segments/{show_id}/ for the streamer
  6. Mark messages as read

Usage:
    uv run python listener_response_generator.py          # Process pending messages
    uv run python listener_response_generator.py --status  # Show unread count
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import os
# Ensure Claude CLI can run (may be blocked inside a Claude Code session)
os.environ.pop("CLAUDECODE", None)

from helpers import log, preprocess_for_tts, run_claude, render_single_voice, get_audio_duration
from persona import build_host_prompt, get_host, STATION_NAME
from ledger import append_event, event_id, ingest_messages

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEDULE_PATH = PROJECT_ROOT / "config" / "schedule.yaml"
OUTPUT_DIR = PROJECT_ROOT / "output" / "talk_segments"
SCRIPTS_DIR = PROJECT_ROOT / "output" / "scripts"
MESSAGES_FILE = Path.home() / ".writ" / "messages.json"

sys.path.insert(0, str(PROJECT_ROOT / "mac"))
from schedule import load_schedule, slot_key

# Short segments for quick turnaround
WORD_TARGET_SINGLE = (100, 200)   # One message: short personal reply
WORD_TARGET_BATCH = (250, 400)    # 2-3 messages: mini mailbag
MAX_BATCH = 3                     # Max messages per segment

# Minimum message length to bother responding to
MIN_MESSAGE_LENGTH = 2


# =============================================================================
# MESSAGE HANDLING
# =============================================================================


def load_messages() -> list[dict]:
    """Load all messages from the messages file."""
    if not MESSAGES_FILE.exists():
        return []
    try:
        return json.loads(MESSAGES_FILE.read_text())
    except Exception:
        return []


def save_messages(messages: list[dict]) -> None:
    """Write messages back to file."""
    MESSAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    MESSAGES_FILE.write_text(json.dumps(messages, indent=2))


def get_unread_messages() -> list[dict]:
    """Get messages that haven't been processed yet."""
    messages = load_messages()
    unread = [
        m for m in messages
        if not m.get("read", False)
        and len(m.get("message", "").strip()) >= MIN_MESSAGE_LENGTH
    ]
    return unread


def mark_messages_read(timestamps: list[str]) -> None:
    """Mark specific messages as read by timestamp."""
    messages = load_messages()
    ts_set = set(timestamps)
    now = datetime.now().isoformat()
    for m in messages:
        if m.get("timestamp") in ts_set:
            m["read"] = True
            m["processed_at"] = now
            m["processing_note"] = "listener_response_daemon"
    save_messages(messages)


# =============================================================================
# PROMPT BUILDING
# =============================================================================


def format_messages_for_prompt(messages: list[dict]) -> str:
    """Format listener messages for the generation prompt."""
    lines = []
    for i, m in enumerate(messages, 1):
        msg = m["message"].strip()
        ts = m.get("timestamp", "")
        # Parse timestamp for relative time
        time_note = ""
        if ts:
            try:
                msg_time = datetime.fromisoformat(ts)
                delta = datetime.now() - msg_time
                if delta.days > 0:
                    time_note = f" (sent {delta.days} day{'s' if delta.days > 1 else ''} ago)"
                elif delta.seconds > 3600:
                    hours = delta.seconds // 3600
                    time_note = f" (sent {hours} hour{'s' if hours > 1 else ''} ago)"
                else:
                    time_note = " (just now)"
            except Exception:
                pass
        lines.append(f"  Message {i}{time_note}: \"{msg}\"")
    return "\n".join(lines)


def build_response_prompt(
    host_id: str,
    show_name: str,
    show_description: str,
    topic_focus: str,
    messages: list[dict],
) -> str:
    """Build the prompt for generating a listener response segment."""
    show_context = {
        "show_name": show_name,
        "show_description": show_description,
        "topic_focus": topic_focus,
        "segment_type": "listener_response",
    }
    base = build_host_prompt(host_id, show_context)

    msg_text = format_messages_for_prompt(messages)
    count = len(messages)

    if count == 1:
        min_w, max_w = WORD_TARGET_SINGLE
    else:
        min_w, max_w = WORD_TARGET_BATCH

    prompt = f"""{base}

SEGMENT: Listener Response (PRIORITY — these are REAL messages from listeners)

You have received {count} real message{'s' if count > 1 else ''} from listener{'s' if count > 1 else ''} \
through the {STATION_NAME} website. Respond on air.

MESSAGES:
{msg_text}

Guidelines:
- Read each message aloud (paraphrase very short or unclear ones naturally)
- Respond to each with genuine warmth and your personality
- For song requests you can't play, acknowledge the taste and riff on why that artist matters
- For greetings from specific places, acknowledge the geography warmly
- For questions about the station, answer in character with mystery and charm
- If a message is in another language, acknowledge it warmly — you can respond in English
- This is part of the natural flow of the show, not a separate formal segment
- Keep to {min_w}-{max_w} words total
- Use [pause] between different messages
- Output ONLY the spoken words. No headers, labels, or stage directions besides [pause]."""

    return prompt


# TTS rendering imported from helpers: render_single_voice, get_audio_duration


# =============================================================================
# MAIN PIPELINE
# =============================================================================


def process_messages(max_batch: int = MAX_BATCH) -> int:
    """Process unread listener messages and generate on-air responses.

    Returns number of messages processed.
    """
    unread = get_unread_messages()
    if not unread:
        return 0

    ingest_messages()
    log(f"Found {len(unread)} unread message(s)")

    # Load schedule for current show context and current slot
    try:
        schedule = load_schedule(SCHEDULE_PATH)
        resolved = schedule.resolve()
        show_id = resolved.show_id
        show_name = resolved.name
        show_description = resolved.description
        host_id = resolved.host
        topic_focus = resolved.topic_focus
        voice = dict(resolved.voices).get("host", get_host(host_id)["tts_voice"])
        slot = slot_key(schedule.airing_start())
    except Exception as e:
        log(f"Schedule error, using defaults: {e}")
        show_id = "midnight_signal"
        show_name = "Midnight Signal"
        show_description = "Philosophy and late-night transmissions."
        host_id = "liminal_operator"
        topic_focus = "philosophy"
        voice = "am_michael"
        slot = datetime.now().strftime("%Y-%m-%d_%H00")

    log(f"Current show: {show_name} (host: {host_id}, voice: {voice})")
    log(f"Writing into slot: {slot}")

    # Process in batches
    total_processed = 0
    while unread:
        batch = unread[:max_batch]
        unread = unread[max_batch:]

        msg_preview = "; ".join(m["message"][:40] for m in batch)
        log(f"Processing batch of {len(batch)}: {msg_preview}...")

        # Generate script
        prompt = build_response_prompt(
            host_id=host_id,
            show_name=show_name,
            show_description=show_description,
            topic_focus=topic_focus,
            messages=batch,
        )

        script = run_claude(prompt, timeout=120, min_length=30)
        if not script:
            log("  Script generation failed, skipping batch")
            # Still mark as read so we don't retry endlessly
            mark_messages_read([m["timestamp"] for m in batch])
            total_processed += len(batch)
            continue

        word_count = len(script.split())
        log(f"  Generated {word_count} words")

        # Prepare TTS
        processed = preprocess_for_tts(script)

        # Output path — into current slot folder (plays this airing only)
        slot_dir = OUTPUT_DIR / show_id / slot
        slot_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = slot_dir / f"listener_response_{timestamp}.wav"

        log("  Rendering audio...")
        if render_single_voice(processed, output_path, voice):
            duration = get_audio_duration(output_path)
            duration_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "?"
            log(f"  Created: {output_path.name} ({duration_str})")

            # Save script metadata
            SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
            meta_path = SCRIPTS_DIR / f"listener_response_{timestamp}.json"
            meta_path.write_text(json.dumps({
                "type": "listener_response",
                "show_id": show_id,
                "show_name": show_name,
                "host": host_id,
                "messages": [m["message"] for m in batch],
                "script": script,
                "word_count": word_count,
                "duration_seconds": duration,
                "voice": voice,
                "generated_at": datetime.now().isoformat(),
            }, indent=2))
            append_event({
                "id": event_id("resp", str(output_path), datetime.now().isoformat(timespec="seconds")),
                "type": "listener_response_generated",
                "time": datetime.now().isoformat(timespec="seconds"),
                "show_id": show_id,
                "host": host_id,
                "messages": [m["message"] for m in batch],
                "path": str(output_path),
                "word_count": word_count,
                "duration_seconds": duration,
                "tags": ["listener_response", show_id],
            })
        else:
            log("  TTS rendering failed")

        # Mark as read regardless (don't retry failed messages forever)
        mark_messages_read([m["timestamp"] for m in batch])
        total_processed += len(batch)

        # Brief pause between batches
        if unread:
            time.sleep(2)

    return total_processed


# =============================================================================
# CLI
# =============================================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="WRIT-FM Listener Response Generator")
    parser.add_argument("--status", action="store_true", help="Show unread message count")
    parser.add_argument("--max-batch", type=int, default=MAX_BATCH, help="Max messages per segment")
    args = parser.parse_args()

    if args.status:
        unread = get_unread_messages()
        total = len(load_messages())
        print(f"Messages: {total} total, {len(unread)} unread")
        if unread:
            for m in unread[:5]:
                print(f"  [{m.get('timestamp', '?')[:16]}] {m['message'][:60]}")
            if len(unread) > 5:
                print(f"  ... and {len(unread) - 5} more")
        return 0

    processed = process_messages(args.max_batch)
    if processed:
        log(f"Processed {processed} message(s)")
    else:
        log("No unread messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
