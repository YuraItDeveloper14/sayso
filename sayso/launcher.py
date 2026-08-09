"""Opening things that are not web pages.

"Open downloads" should open the folder, and "open VS Code" should start the
editor. Windows already keeps an index of everything installed - the Start Menu
is a folder of shortcuts - so apps are found by reading it rather than by
maintaining a list that goes stale.
"""

import os
import re
import threading
from pathlib import Path

HOME = Path(os.environ.get("USERPROFILE", Path.home()))

# Spoken name to folder. Deliberately does not include "docs", which people say
# when they mean Google Docs.
FOLDERS = {
    "downloads": HOME / "Downloads",
    "download": HOME / "Downloads",
    "documents": HOME / "Documents",
    "desktop": HOME / "Desktop",
    "pictures": HOME / "Pictures",
    "photos": HOME / "Pictures",
    "music": HOME / "Music",
    "videos": HOME / "Videos",
    # Not "home folder": the trailing word is stripped before lookup.
    "home": HOME,
}

START_MENUS = [
    Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
]

# Whisper writes these the long way round; the shortcut is named the short way.
APP_ALIASES = {
    "vs code": "visual studio code",
    "vscode": "visual studio code",
    "ps": "powershell",
    "cmd": "command prompt",
    "explorer": "file explorer",
    "task manager": "task manager",
}

_cache_lock = threading.Lock()
_shortcuts = None


def _normalize(name):
    return re.sub(r"[^a-z0-9 ]", "", name.strip().lower())


def _load_shortcuts():
    """Every .lnk under both Start Menus, as (normalized name, path)."""
    global _shortcuts
    with _cache_lock:
        if _shortcuts is not None:
            return _shortcuts
        found = []
        for root in START_MENUS:
            if not root.is_dir():
                continue
            try:
                for path in root.rglob("*.lnk"):
                    found.append((_normalize(path.stem), path))
            except OSError:
                continue
        _shortcuts = found
        return _shortcuts


def refresh():
    global _shortcuts
    with _cache_lock:
        _shortcuts = None


def find_folder(name):
    key = _normalize(name)
    key = re.sub(r"\s*(?:folder|directory)$", "", key).strip()
    path = FOLDERS.get(key)
    return path if path and path.is_dir() else None


def find_app(name):
    key = APP_ALIASES.get(_normalize(name), _normalize(name))
    if not key:
        return None

    shortcuts = _load_shortcuts()

    for candidate, path in shortcuts:
        if candidate == key:
            return path
    for candidate, path in shortcuts:
        if candidate.startswith(key):
            return path

    # Last resort: every spoken word appears somewhere in the shortcut name.
    words = key.split()
    if len(key) < 4:
        return None
    for candidate, path in shortcuts:
        if all(word in candidate for word in words):
            return path
    return None


def resolve(name):
    """(kind, label, path) for something local, or (None, None, None)."""
    folder = find_folder(name)
    if folder is not None:
        return "folder", folder.name or str(folder), folder

    app = find_app(name)
    if app is not None:
        return "app", app.stem, app

    return None, None, None


def launch(path):
    os.startfile(str(path))
