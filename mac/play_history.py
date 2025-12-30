#!/usr/bin/env python3
"""
WVOID-FM Play History Tracker

Tracks all played tracks to prevent repeats and enable analytics.
Uses SQLite for persistent storage.
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

# Default database location
DEFAULT_DB_PATH = Path.home() / ".wvoid" / "history.db"


class PlayHistory:
    """Track play history with SQLite backend."""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS plays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filepath TEXT NOT NULL,
                    track_name TEXT,
                    artist TEXT,
                    vibe TEXT,
                    time_period TEXT,
                    listeners INTEGER DEFAULT 0,
                    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_filepath ON plays(filepath)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_played_at ON plays(played_at)
            """)
            conn.commit()

    def record_play(
        self,
        filepath: str,
        track_name: str = None,
        artist: str = None,
        vibe: str = None,
        time_period: str = None,
        listeners: int = 0,
    ):
        """Record a track play."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO plays (filepath, track_name, artist, vibe, time_period, listeners)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (filepath, track_name, artist, vibe, time_period, listeners),
            )
            conn.commit()

    def was_played_recently(self, filepath: str, hours: int = 24) -> bool:
        """Check if track was played within the last N hours."""
        cutoff = datetime.now() - timedelta(hours=hours)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM plays
                WHERE filepath = ? AND played_at > ?
                """,
                (filepath, cutoff.isoformat()),
            )
            count = cursor.fetchone()[0]
            return count > 0

    def get_recent_plays(self, limit: int = 50) -> list[dict]:
        """Get recent plays."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT filepath, track_name, artist, vibe, time_period, listeners, played_at
                FROM plays
                ORDER BY played_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_play_count(self, filepath: str) -> int:
        """Get total play count for a track."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM plays WHERE filepath = ?",
                (filepath,),
            )
            return cursor.fetchone()[0]

    def get_most_played(self, limit: int = 20) -> list[dict]:
        """Get most frequently played tracks."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT filepath, track_name, COUNT(*) as play_count,
                       SUM(listeners) as total_listeners,
                       MAX(played_at) as last_played
                FROM plays
                GROUP BY filepath
                ORDER BY play_count DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get overall statistics."""
        with sqlite3.connect(self.db_path) as conn:
            # Total plays
            total = conn.execute("SELECT COUNT(*) FROM plays").fetchone()[0]

            # Unique tracks
            unique = conn.execute(
                "SELECT COUNT(DISTINCT filepath) FROM plays"
            ).fetchone()[0]

            # Total listeners served
            listeners = conn.execute(
                "SELECT SUM(listeners) FROM plays"
            ).fetchone()[0] or 0

            # Plays by time period
            cursor = conn.execute(
                """
                SELECT time_period, COUNT(*) as count
                FROM plays
                GROUP BY time_period
                """
            )
            by_period = {row[0]: row[1] for row in cursor.fetchall()}

            # Plays by vibe
            cursor = conn.execute(
                """
                SELECT vibe, COUNT(*) as count
                FROM plays
                WHERE vibe IS NOT NULL
                GROUP BY vibe
                ORDER BY count DESC
                """
            )
            by_vibe = {row[0]: row[1] for row in cursor.fetchall()}

            # First and last play
            first = conn.execute(
                "SELECT MIN(played_at) FROM plays"
            ).fetchone()[0]
            last = conn.execute(
                "SELECT MAX(played_at) FROM plays"
            ).fetchone()[0]

            return {
                "total_plays": total,
                "unique_tracks": unique,
                "total_listeners": listeners,
                "by_time_period": by_period,
                "by_vibe": by_vibe,
                "first_play": first,
                "last_play": last,
            }

    def filter_recent(self, tracks: list[Path], hours: int = 24) -> list[Path]:
        """Filter out tracks played recently."""
        return [t for t in tracks if not self.was_played_recently(str(t), hours)]


# Global instance for easy import
_history: Optional[PlayHistory] = None


def get_history() -> PlayHistory:
    """Get or create the global PlayHistory instance."""
    global _history
    if _history is None:
        _history = PlayHistory()
    return _history


# CLI interface
if __name__ == "__main__":
    import sys

    history = get_history()

    if len(sys.argv) < 2:
        print("Usage: play_history.py [stats|recent|most_played]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "stats":
        stats = history.get_stats()
        print(json.dumps(stats, indent=2, default=str))

    elif cmd == "recent":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        plays = history.get_recent_plays(limit)
        for p in plays:
            print(f"{p['played_at'][:19]} | {p['track_name'] or p['filepath']}")

    elif cmd == "most_played":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        tracks = history.get_most_played(limit)
        for t in tracks:
            print(f"{t['play_count']:3d}x | {t['track_name'] or t['filepath']}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
