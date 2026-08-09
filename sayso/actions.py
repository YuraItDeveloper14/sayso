"""Execute a parsed Intent: drive the browser, edit notes, talk back.

Anything that changes stored state also registers how to reverse itself, so
"undo that" can take back a misheard command. Anything that leaves the machine -
a page opened, a note already copied to Notion - deliberately does not, because
pretending it could be undone would be a lie.
"""

import re
import threading
import time
import webbrowser
from dataclasses import dataclass, field

from . import launcher
from .aliases import store as alias_store
from .config import settings
from .connectors import registry
from .events import bus
from .extension import bridge
from .intents import SEARCH_ENGINES, _search_url, resolve_target, split_targets
from .notes import store
from .sounds import sounds
from .timers import humanize, scheduler
from .undo import stack

BROWSER_ACTION_NAMES = {
    "close_tab": "Closed the tab",
    "new_tab": "Opened a new tab",
    "reopen_tab": "Reopened the last tab",
    "next_tab": "Next tab",
    "previous_tab": "Previous tab",
    "reload": "Reloaded the page",
    "scroll_up": "Scrolled up",
    "scroll_down": "Scrolled down",
    "scroll_top": "Jumped to the top",
    "scroll_bottom": "Jumped to the bottom",
}


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


# ------------------------------------------------------------------ opening


def _open_one(target):
    """Open one destination, local or web. Returns (label, url or None)."""
    kind, label, path = launcher.resolve(target)
    if path is not None:
        launcher.launch(path)
        return label, None

    label, url = resolve_target(target, _following_alias=True)
    if not url:
        label, url = _search_url("google", target)
    _open(url)
    return label, url


def open_site(target):
    # A phrase you taught outranks everything, including an installed app of
    # the same name - you said explicitly what you meant by it. It can also
    # name several things at once: "when I say let's work, open notion and
    # github" is one phrase and two windows.
    taught = alias_store.lookup(target)
    if taught is not None:
        labels, urls = [], []
        for part in split_targets(taught):
            label, url = _open_one(part)
            labels.append(label)
            if url:
                urls.append(url)
            if len(labels) < len(split_targets(taught)):
                time.sleep(0.25)  # let the browser settle between tabs
        joined = ", ".join(labels)
        return Result(True, f"Opened {joined}", f"Opening {joined}", urls)

    kind, label, path = launcher.resolve(target)
    if path is not None:
        launcher.launch(path)
        return Result(True, f"Opened {label} ({kind})", f"Opening {label}")

    label, url = resolve_target(target)
    if not url:
        # Multi-word and not a domain, so the user meant a search.
        label, url = _search_url("google", target)
        _open(url)
        return Result(True, f'Searched Google for "{target}"', f"Searching for {target}", [url])
    _open(url)
    return Result(True, f"Opened {label}", f"Opening {label}", [url])


def noise():
    """Something was heard, but it was not speech."""
    return Result(False, "Did not catch that — try again", "")


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
    return Result(True, f'Searched {label} for "{query}"', f"Searching {label} for {query}", [url])


# -------------------------------------------------------------------- notes


def _mirror_to_connectors(texts):
    """Send notes on to Obsidian and friends, off the critical path.

    A connector can take seconds - an MCP server may have to start up - and the
    note is already saved locally, so none of that is worth making the user
    wait for.
    """
    if not registry.active():
        return

    def deliver():
        for text in texts:
            for name, ok, detail in registry.deliver_note(text):
                bus.publish("connector", connector=name, ok=ok, detail=detail, text=text)

    threading.Thread(target=deliver, daemon=True, name="sayso-connectors").start()


def write_note(text, source="voice"):
    cleaned = _tidy_note(text)
    if not cleaned:
        return Result(False, "Nothing to write down", "I did not catch the note")

    created = store.add(cleaned, source=source)
    ids = [n["id"] for n in created]
    stack.record(
        f"writing {len(created)} note{'s' if len(created) != 1 else ''}",
        lambda: store.delete_many(ids),
    )
    _mirror_to_connectors([n["text"] for n in created])

    live = [c.name for c in registry.active()]
    suffix = f" → {', '.join(live)}" if live else ""

    if len(created) == 1:
        return Result(True, f"Noted: {created[0]['text']}{suffix}", "Noted")
    joined = "; ".join(n["text"] for n in created)
    return Result(True, f"Noted {len(created)} items: {joined}{suffix}", f"Noted {len(created)} items")


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
    stack.record(f'checking off "{note["text"]}"', lambda: store.toggle(note["id"]))
    return Result(True, f"Checked off: {note['text']}", f"Done: {note['text']}")


def delete_note(position):
    note = store.by_position(position)
    if not note:
        return Result(False, f"No note at position {position}", "I could not find that note")
    store.delete(note["id"])
    stack.record(f'deleting "{note["text"]}"', lambda: store.restore([note]))
    return Result(True, f"Deleted: {note['text']}", f"Deleted {note['text']}")


def clear_notes():
    before = store.all()
    count = store.clear()
    if not count:
        return Result(True, "There was nothing to clear", "Your list was already empty")
    stack.record(f"clearing {count} notes", lambda: store.restore(before))
    return Result(True, f"Cleared {count} notes", f"Cleared {count} notes")


# ------------------------------------------------------------------- timers


def set_timer(seconds, label):
    if seconds <= 0:
        return Result(False, "That is not a length of time", "I did not catch how long")
    timer = scheduler.add(seconds, label)
    stack.record(f"the {humanize(seconds)} timer", lambda: scheduler.cancel(timer["id"]))
    spoken_length = humanize(seconds)
    what = f" to {timer['label']}" if label else ""
    return Result(True, f"Timer set for {spoken_length}{what}", f"Timer set for {spoken_length}{what}")


def cancel_timers():
    count = scheduler.cancel_all()
    if not count:
        return Result(True, "No timers were running", "No timers were running")
    return Result(True, f"Cancelled {count} timers", f"Cancelled {count} timers")


def list_timers():
    active = scheduler.active()
    if not active:
        return Result(True, "No timers running", "No timers running")
    parts = [f"{t['label']} in {humanize(t['remaining'])}" for t in active]
    return Result(True, " | ".join(parts), ". ".join(parts))


def dismiss_alarm():
    if sounds.stop_alarm():
        return Result(True, "Alarm off", "")
    return Result(True, "Nothing was ringing", "")


# ---------------------------------------------------------------- shortcuts


def teach_alias(phrase, target):
    saved = alias_store.add(phrase, target)
    if not saved:
        return Result(False, "That shortcut needs a name", "I did not catch the phrase")
    stack.record(f'the shortcut "{saved["phrase"]}"', lambda: alias_store.remove(saved["phrase"]))
    label, url = resolve_target(saved["target"])
    where = url or saved["target"]
    return Result(
        True,
        f'"{saved["phrase"]}" now opens {where}',
        f"Got it. {saved['phrase']} now opens {label or 'that'}",
    )


def forget_alias(phrase):
    removed = alias_store.remove(phrase)
    if not removed:
        return Result(False, f'No shortcut called "{phrase}"', "I do not know that shortcut")
    stack.record(
        f'forgetting "{removed["phrase"]}"',
        lambda: alias_store.add(removed["phrase"], removed["target"]),
    )
    return Result(True, f'Forgot "{removed["phrase"]}"', f"Forgot {removed['phrase']}")


# -------------------------------------------------------------------- undo


def undo():
    description = stack.undo()
    if description is None:
        return Result(False, "Nothing to undo", "There is nothing to undo")
    return Result(True, f"Undid {description}", f"Undid {description}")


# ------------------------------------------------------------------ browser


def browser_action(action):
    label = BROWSER_ACTION_NAMES.get(action, action)
    if not bridge.send(action):
        return Result(
            False,
            "No browser extension connected — install it from the extension folder",
            "The browser extension is not connected",
        )
    return Result(True, label, "")


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
    "set_timer": lambda p: set_timer(p["seconds"], p["label"]),
    "cancel_timers": lambda p: cancel_timers(),
    "list_timers": lambda p: list_timers(),
    "dismiss_alarm": lambda p: dismiss_alarm(),
    "teach_alias": lambda p: teach_alias(p["phrase"], p["target"]),
    "forget_alias": lambda p: forget_alias(p["phrase"]),
    "undo": lambda p: undo(),
    "browser": lambda p: browser_action(p["action"]),
    "noise": lambda p: noise(),
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
