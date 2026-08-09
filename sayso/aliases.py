"""Phrases you teach Sayso.

"When I say my class, open <url>" writes an entry here, and from then on
"open my class" resolves through this store before the built-in site list. It is
the difference between a fixed set of commands and something that learns your
vocabulary.
"""

import json
import re
import threading
import time

from .config import DATA_DIR

ALIASES_FILE = DATA_DIR / "aliases.json"


def normalize_phrase(phrase):
    cleaned = phrase.strip().lower()
    cleaned = re.sub(r"^(?:the|my|a)\s+", "", cleaned)
    cleaned = re.sub(r"[^\w\s.:/-]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class AliasStore:
    def __init__(self, path=ALIASES_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._aliases = self._read()

    def _read(self):
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _write(self):
        self._path.write_text(
            json.dumps(self._aliases, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def add(self, phrase, target):
        key = normalize_phrase(phrase)
        if not key:
            return None
        with self._lock:
            self._aliases[key] = {"target": target.strip(), "taught": time.time()}
            self._write()
        return {"phrase": key, "target": target.strip()}

    def remove(self, phrase):
        key = normalize_phrase(phrase)
        with self._lock:
            removed = self._aliases.pop(key, None)
            if removed:
                self._write()
        return {"phrase": key, **removed} if removed else None

    def lookup(self, phrase):
        key = normalize_phrase(phrase)
        with self._lock:
            entry = self._aliases.get(key)
        return entry["target"] if entry else None

    def all(self):
        with self._lock:
            return [
                {"phrase": phrase, "target": entry["target"], "taught": entry["taught"]}
                for phrase, entry in sorted(self._aliases.items())
            ]

    def clear(self):
        with self._lock:
            count = len(self._aliases)
            self._aliases = {}
            self._write()
        return count


store = AliasStore()
