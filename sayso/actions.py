"""Execute a parsed Intent: drive the browser, edit notes, talk back."""

import re
import time
import webbrowser
from dataclasses import dataclass, field

from .config import settings
from .intents import SEARCH_ENGINES, _search_url, resolve_target
from .notes import store


@dataclass
class Result:
    ok: bool
    display: str
    say: str = ""
    opened: list = field(default_factory=list)

    def as_dict(self):
        return {
            "ok": self.ok,
            "display": self.display,
            "say": self.say,
            "opened": self.opened,
        }


def _open(url):
    webbrowser.open(url, new=2, autoraise=True)


def _tidy_note(text):
    """Strip the connective tissue dictation leaves behind."""
    cleaned = re.sub(r"^(?:that|to)\s+", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"^i\s+(?:need|have|want)\s+to\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" .,")


def _spoken_list(notes):
    """Render notes as something that sounds natural read aloud."""
    if not notes:
        return "Your list is empty."
    if len(notes) == 1:
        return f"One thing on your list: {notes[0]['text']}."
    lines = [f"You have {len(notes)} things on your list."]
    for i, note in enumerate(notes, 1):
        lines.append(f"{i}. {note['text']}.")
    return " ".join(lines)


def open_site(target):
    label, url = resolve_target(target)
    if not url:
        # Multi-word and not a domain, so the user meant a search.
        label, url = _search_url("google", target)
        _open(url)
        return Result(True, f'Searched Google for "{target}"', f"Searching for {target}", [url])
    _open(url)
    return Result(True, f"Opened {label}", f"Opening {label}", [url])


def open_via_google(target):
    """The manual route, automated: Google first, then the destination."""
    label, url = resolve_target(target)
    if not url:
        return search(target)

    _, google_url = _search_url("google", target)
    _open(google_url)
    time.sleep(settings.google_hop_delay)
    _open(url)
    return Result(
        True,
        f"Went through Google, then opened {label}",
        f"Going through Google to {label}",
        [google_url, url],
    )


def search(query):
    label, url = _search_url("google", query)
    _open(url)
    return Result(True, f'Searched Google for "{query}"', f"Searching for {query}", [url])


def site_search(query, engine):
    if engine not in SEARCH_ENGINES:
        engine = "google"
    label, url = _search_url(engine, query)
    _open(url)
    return Result(
        True,
        f'Searched {label} for "{query}"',
        f"Searching {label} for {query}",
        [url],
    )


def write_note(text, source="voice"):
    cleaned = _tidy_note(text)
    if not cleaned:
        return Result(False, "Nothing to write down", "I did not catch the note")
    created = store.add(cleaned, source=source)
    if len(created) == 1:
        return Result(True, f"Noted: {created[0]['text']}", "Noted")
    joined = "; ".join(n["text"] for n in created)
    return Result(True, f"Noted {len(created)} items: {joined}", f"Noted {len(created)} items")


def read_notes():
    pending = store.pending()
    spoken = _spoken_list(pending)
    if not pending:
        return Result(True, "Your list is empty", spoken)
    listed = " | ".join(f"{i}. {n['text']}" for i, n in enumerate(pending, 1))
    return Result(True, listed, spoken)


def complete_note(position):
    note = store.by_position(position)
    if not note:
        return Result(False, f"No note at position {position}", "I could not find that note")
    store.toggle(note["id"])
    return Result(True, f"Checked off: {note['text']}", f"Done: {note['text']}")


def delete_note(position):
    note = store.by_position(position)
    if not note:
        return Result(False, f"No note at position {position}", "I could not find that note")
    store.delete(note["id"])
    return Result(True, f"Deleted: {note['text']}", f"Deleted {note['text']}")


def clear_notes():
    count = store.clear()
    if not count:
        return Result(True, "There was nothing to clear", "Your list was already empty")
    return Result(True, f"Cleared {count} notes", f"Cleared {count} notes")


HANDLERS = {
    "open_site": lambda p: open_site(p["target"]),
    "open_via_google": lambda p: open_via_google(p["target"]),
    "search": lambda p: search(p["query"]),
    "site_search": lambda p: site_search(p["query"], p["engine"]),
    "write_note": lambda p: write_note(p["text"], p.get("source", "voice")),
    "read_notes": lambda p: read_notes(),
    "complete_note": lambda p: complete_note(p["position"]),
    "delete_note": lambda p: delete_note(p["position"]),
    "clear_notes": lambda p: clear_notes(),
}


def execute(intent):
    handler = HANDLERS.get(intent.name)
    if handler is None:
        heard = intent.normalized or intent.raw
        return Result(
            False,
            f'Not a command I know: "{heard}"' if heard else "Nothing was said",
            "Sorry, I did not catch a command",
        )
    try:
        return handler(intent.params)
    except Exception as exc:
        return Result(False, f"{intent.name} failed: {exc}", "That did not work")
