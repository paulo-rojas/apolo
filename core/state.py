import sqlite3
from pathlib import Path
import json
from typing import Any, Dict


class State:
    def __init__(self, path: str = None):
        self._path = path or str(Path.cwd() / "memory" / "apolo_state.db")
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._ensure_table()
        self._cache: Dict[str, Any] = {}

    def _ensure_table(self):
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        self._conn.commit()

    def get(self, key: str, default=None):
        if key in self._cache:
            return self._cache[key]
        cur = self._conn.cursor()
        cur.execute("SELECT value FROM kv WHERE key=?", (key,))
        row = cur.fetchone()
        if not row:
            return default
        val = json.loads(row[0])
        self._cache[key] = val
        return val

    def set(self, key: str, value: Any):
        self._cache[key] = value
        cur = self._conn.cursor()
        cur.execute(
            "REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value))
        )
        self._conn.commit()
