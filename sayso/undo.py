"""Taking back the last thing SaySo did.

Speech recognition is never perfect, so the interesting question is not whether
it mishears you but how fast you can recover when it does. Every action that
changes stored state registers how to reverse itself here.

Actions that leave the machine - a page opened, a note already copied to Notion -
are deliberately not undoable. Pretending otherwise would be a lie.
"""

import threading

DEPTH = 10


class UndoStack:
    def __init__(self):
        self._entries = []
        self._lock = threading.Lock()

    def record(self, description, revert):
        """`revert` is called with no arguments and puts things back."""
        with self._lock:
            self._entries.append({"description": description, "revert": revert})
            del self._entries[:-DEPTH]

    def undo(self):
        with self._lock:
            entry = self._entries.pop() if self._entries else None
        if entry is None:
            return None
        entry["revert"]()
        return entry["description"]

    @property
    def last(self):
        with self._lock:
            return self._entries[-1]["description"] if self._entries else None

    def clear(self):
        with self._lock:
            self._entries = []


stack = UndoStack()
