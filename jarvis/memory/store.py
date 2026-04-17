import sqlite3
import json
import logging
import os
from datetime import datetime

log = logging.getLogger("jarvis.memory")


class MemoryStore:
    def __init__(self, db_path):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()
        log.info(f"Memory store: {db_path}")

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routines (
                name       TEXT PRIMARY KEY,
                steps      TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS phrase_mappings (
                phrase     TEXT PRIMARY KEY,
                intent     TEXT NOT NULL,
                slots      TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS action_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                intent    TEXT NOT NULL,
                raw_text  TEXT,
                slots     TEXT,
                timestamp TEXT NOT NULL
            );
        """)
        self._conn.commit()

    # ── Preferences ─────────────────────────────────────────────

    def get_preference(self, key, default=None):
        row = self._conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        return json.loads(row["value"]) if row else default

    def set_preference(self, key, value):
        self._conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value, updated_at) "
            "VALUES (?, ?, ?)",
            (key, json.dumps(value), datetime.now().isoformat()),
        )
        self._conn.commit()

    # ── Routines ────────────────────────────────────────────────

    def get_routine(self, name):
        row = self._conn.execute(
            "SELECT steps FROM routines WHERE name = ?", (name,)
        ).fetchone()
        return json.loads(row["steps"]) if row else None

    def save_routine(self, name, steps):
        self._conn.execute(
            "INSERT OR REPLACE INTO routines (name, steps, updated_at) "
            "VALUES (?, ?, ?)",
            (name, json.dumps(steps), datetime.now().isoformat()),
        )
        self._conn.commit()

    def list_routines(self):
        rows = self._conn.execute("SELECT name FROM routines").fetchall()
        return [r["name"] for r in rows]

    # ── Phrase Mappings ─────────────────────────────────────────

    def get_phrase_mapping(self, phrase):
        row = self._conn.execute(
            "SELECT intent, slots FROM phrase_mappings WHERE phrase = ?",
            (phrase,),
        ).fetchone()
        if row:
            return {
                "intent": row["intent"],
                "slots": json.loads(row["slots"]) if row["slots"] else {},
            }
        return None

    def save_phrase_mapping(self, phrase, intent, slots=None):
        self._conn.execute(
            "INSERT OR REPLACE INTO phrase_mappings "
            "(phrase, intent, slots, created_at) VALUES (?, ?, ?, ?)",
            (phrase.lower(), intent, json.dumps(slots or {}),
             datetime.now().isoformat()),
        )
        self._conn.commit()

    # ── Action Log ──────────────────────────────────────────────

    def log_action(self, intent, raw_text, slots=None):
        self._conn.execute(
            "INSERT INTO action_log (intent, raw_text, slots, timestamp) "
            "VALUES (?, ?, ?, ?)",
            (intent, raw_text, json.dumps(slots or {}),
             datetime.now().isoformat()),
        )
        # Auto-prune to last 100 entries
        self._conn.execute(
            "DELETE FROM action_log WHERE id NOT IN "
            "(SELECT id FROM action_log ORDER BY id DESC LIMIT 100)"
        )
        self._conn.commit()

    def get_recent_actions(self, limit=10):
        rows = self._conn.execute(
            "SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Reset ───────────────────────────────────────────────────

    def reset(self):
        """Wipe all memory. Jarvis forgets everything."""
        self._conn.executescript("""
            DELETE FROM preferences;
            DELETE FROM routines;
            DELETE FROM phrase_mappings;
            DELETE FROM action_log;
        """)
        self._conn.commit()
        log.info("Memory wiped.")

    def close(self):
        self._conn.close()
