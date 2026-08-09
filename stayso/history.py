"""Rolling log of everything StaySo heard and did, kept for the dashboard."""

import json
import threading
import time

from .config import HISTORY_FILE

MAX_ENTRIES = 200


class History:
    def __init__(self, path=HISTORY_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._entries = self._read()

    def _read(self):
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _write(self):
        self._path.write_text(
            json.dumps(self._entries[-MAX_ENTRIES:], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(self, transcript, intent, result, source="voice", latency=None):
        entry = {
            "id": int(time.time() * 1000),
            "ts": time.time(),
            "transcript": transcript,
            "intent": intent,
            "ok": result.ok,
            "display": result.display,
            "opened": result.opened,
            "source": source,
            "latency": round(latency, 2) if latency else None,
        }
        with self._lock:
            self._entries.append(entry)
            self._entries = self._entries[-MAX_ENTRIES:]
            self._write()
        return entry

    def recent(self, limit=40):
        with self._lock:
            return list(reversed(self._entries[-limit:]))

    def clear(self):
        with self._lock:
            self._entries = []
            self._write()


history = History()
