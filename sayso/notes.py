"""Note storage. Plain JSON on disk so nothing is lost when the daemon stops."""

import json
import re
import threading
import time

from .config import NOTES_FILE

# Whisper punctuates dictation, so "buy milk, call mom, and finish the deck"
# arrives as one blob. Split it into separate notes on the obvious seams.
_SPLIT_PATTERN = re.compile(
    r"\s*(?:[;\n]|,\s*(?:and\s+)?|\.\s+(?=[A-Z])|\band then\b|\balso\b)\s*",
    re.IGNORECASE,
)


def split_into_items(text):
    """Break a dictated sentence into individual note items."""
    parts = [p.strip(" .,;") for p in _SPLIT_PATTERN.split(text)]
    parts = [p for p in parts if len(p) > 1]
    return parts or [text.strip()]


class NoteStore:
    def __init__(self, path=NOTES_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._notes = self._read()

    def _read(self):
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return []
        return []

    def _write(self):
        self._path.write_text(
            json.dumps(self._notes, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _next_id(self):
        return max((n["id"] for n in self._notes), default=0) + 1

    def add(self, text, source="voice"):
        """Add one or more notes from a single dictated string."""
        created = []
        with self._lock:
            for item in split_into_items(text):
                note = {
                    "id": self._next_id(),
                    "text": item[0].upper() + item[1:] if item else item,
                    "done": False,
                    "created": time.time(),
                    "source": source,
                }
                self._notes.append(note)
                created.append(note)
            self._write()
        return created

    def all(self):
        with self._lock:
            return list(self._notes)

    def pending(self):
        with self._lock:
            return [n for n in self._notes if not n["done"]]

    def toggle(self, note_id):
        with self._lock:
            for note in self._notes:
                if note["id"] == note_id:
                    note["done"] = not note["done"]
                    self._write()
                    return note
        return None

    def delete(self, note_id):
        with self._lock:
            for i, note in enumerate(self._notes):
                if note["id"] == note_id:
                    removed = self._notes.pop(i)
                    self._write()
                    return removed
        return None

    def clear(self):
        with self._lock:
            count = len(self._notes)
            self._notes = []
            self._write()
        return count

    def by_position(self, position):
        """Resolve 'note 2' or 'the last note' to an actual note."""
        pending = self.pending()
        if not pending:
            return None
        if position == "last":
            return pending[-1]
        if position == "first":
            return pending[0]
        index = int(position) - 1
        if 0 <= index < len(pending):
            return pending[index]
        return None


store = NoteStore()
