"""Intent parser tests. No audio, no model, no browser - run them anywhere:

    python tests/test_intents.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sayso.intents import parse, resolve_target, split_targets  # noqa: E402

# (spoken text, expected intent, expected params subset)
CASES = [
    # -- opening ---------------------------------------------------------
    ("open YouTube", "open_site", {"target": "youtube"}),
    ("Open up Gmail.", "open_site", {"target": "gmail"}),
    ("go to github", "open_site", {"target": "github"}),
    ("take me to reddit", "open_site", {"target": "reddit"}),
    ("youtube", "open_site", {"target": "youtube"}),
    ("open you tube", "open_site", {"target": "youtube"}),

    # -- the flagship command --------------------------------------------
    ("open YouTube through Google", "open_via_google", {"target": "youtube"}),
    ("open gmail via google", "open_via_google", {"target": "gmail"}),
    ("pull up wikipedia using google", "open_via_google", {"target": "wikipedia"}),

    # -- searching --------------------------------------------------------
    ("google how to pitch a hackathon project", "search",
     {"query": "how to pitch a hackathon project"}),
    ("search for python decorators", "search", {"query": "python decorators"}),
    ("look up the weather in kyiv", "search", {"query": "the weather in kyiv"}),
    ("search lofi beats on youtube", "site_search",
     {"query": "lofi beats", "engine": "youtube"}),
    ("youtube search chopin nocturne", "site_search",
     {"query": "chopin nocturne", "engine": "youtube"}),

    # -- writing notes ----------------------------------------------------
    ("note buy milk", "write_note", {"text": "buy milk"}),
    ("Note: finish the slides.", "write_note", {"text": "finish the slides"}),
    ("take a note call the mentor", "write_note", {"text": "call the mentor"}),
    ("remind me to submit before midnight", "write_note",
     {"text": "submit before midnight"}),
    ("write down that the demo starts at four", "write_note",
     {"text": "that the demo starts at four"}),

    # -- reading notes ----------------------------------------------------
    ("read my notes", "read_notes", {}),
    ("what's on my list", "read_notes", {}),
    ("what do I have today", "read_notes", {}),
    ("show me my tasks", "read_notes", {}),
    ("read back my to-do list", "read_notes", {}),

    # -- managing notes ---------------------------------------------------
    ("check off 2", "complete_note", {"position": 2}),
    ("mark the first task", "complete_note", {"position": 1}),
    ("delete note 3", "delete_note", {"position": 3}),
    ("remove the last note", "delete_note", {"position": "last"}),
    ("clear all my notes", "clear_notes", {}),
    ("delete my notes", "clear_notes", {}),

    # -- timers, which must outrank "remind me to" notes -------------------
    ("remind me in 20 minutes to stretch", "set_timer",
     {"seconds": 1200, "label": "stretch"}),
    ("remind me in a minute to check the oven", "set_timer",
     {"seconds": 60, "label": "check the oven"}),
    ("in 30 seconds remind me to look up", "set_timer",
     {"seconds": 30, "label": "look up"}),
    ("set a timer for 5 minutes", "set_timer", {"seconds": 300, "label": ""}),
    ("set a timer for 2 hours to submit", "set_timer",
     {"seconds": 7200, "label": "submit"}),
    ("10 minute timer", "set_timer", {"seconds": 600}),
    ("cancel all timers", "cancel_timers", {}),
    ("what timers are running", "list_timers", {}),

    # -- teaching shortcuts -----------------------------------------------
    ("when I say my class open https://classroom.google.com", "teach_alias",
     {"phrase": "my class", "target": "https://classroom.google.com"}),
    ("teach that standup means meet.google.com/abc", "teach_alias",
     {"phrase": "standup", "target": "meet.google.com/abc"}),
    ("remember the vault as obsidian.md", "teach_alias",
     {"phrase": "the vault", "target": "obsidian.md"}),
    ("forget my class", "forget_alias", {"phrase": "my class"}),

    # -- and the note phrasings they must not steal ------------------------
    ("remind me to submit before midnight", "write_note",
     {"text": "submit before midnight"}),
    ("remember to charge the laptop", "write_note",
     {"text": "charge the laptop"}),

    # -- undo and silencing an alarm --------------------------------------
    ("undo that", "undo", {}),
    ("scratch that", "undo", {}),
    ("take that back", "undo", {}),
    ("stop", "dismiss_alarm", {}),
    ("quiet", "dismiss_alarm", {}),
    # "ok" is a thing people say for a hundred reasons; it must not be a command.
    ("ok", "noise", {}),

    # -- tab control, handed to the extension ------------------------------
    ("close tab", "browser", {"action": "close_tab"}),
    ("close this tab", "browser", {"action": "close_tab"}),
    ("new tab", "browser", {"action": "new_tab"}),
    ("open a new tab", "browser", {"action": "new_tab"}),
    ("reopen the last closed tab", "browser", {"action": "reopen_tab"}),
    ("next tab", "browser", {"action": "next_tab"}),
    ("go to the previous tab", "browser", {"action": "previous_tab"}),
    ("reload the page", "browser", {"action": "reload"}),
    ("refresh", "browser", {"action": "reload"}),
    ("scroll down", "browser", {"action": "scroll_down"}),
    ("scroll to the top", "browser", {"action": "scroll_top"}),
    ("bottom of the page", "browser", {"action": "scroll_bottom"}),

    # -- and the openings tab control must not steal ------------------------
    ("open youtube", "open_site", {"target": "youtube"}),
    ("open downloads", "open_site", {"target": "downloads"}),

    # -- misheard noise is not the same as an unknown command --------------
    ("", "noise", {}),
    ("Ah, luringy, luringy, luringy, luringy, luringy", "noise", {}),
    ("you", "noise", {}),
    ("Thanks for watching!", "noise", {}),
    ("hmm", "noise", {}),
    ("na na na na", "noise", {}),

    # -- but a real sentence we have no rule for is "unknown" --------------
    ("paint the fence green tomorrow", "unknown", {}),
]

# Multi-step shortcuts: one phrase, several destinations.
SPLIT_CASES = [
    ("notion and github", ["notion", "github"]),
    ("notion, github, gmail", ["notion", "github", "gmail"]),
    ("vs code and then downloads", ["vs code", "downloads"]),
    ("youtube", ["youtube"]),
]

RESOLVE_CASES = [
    ("youtube", "https://www.youtube.com"),
    ("you tube", "https://www.youtube.com"),
    ("the github website", "https://github.com"),
    ("github.com", "https://github.com"),
    ("example.org", "https://example.org"),
    ("notion", "https://www.notion.so"),
    ("figma", "https://www.figma.com"),
    # Unknown words fall through to a search rather than inventing a domain.
    ("someunknownapp", None),
    ("notepad", None),
    ("a long phrase that is not a site", None),
]


def run():
    failures = []

    for text, expected_intent, expected_params in CASES:
        intent = parse(text)
        if intent.name != expected_intent:
            failures.append(
                f'  "{text}"\n      expected intent {expected_intent}, got {intent.name}'
            )
            continue
        for key, value in expected_params.items():
            actual = intent.params.get(key)
            if actual != value:
                failures.append(
                    f'  "{text}"\n      param {key}: expected {value!r}, got {actual!r}'
                )

    for target, expected_url in RESOLVE_CASES:
        _label, url = resolve_target(target)
        if url != expected_url:
            failures.append(
                f'  resolve_target("{target}")\n      expected {expected_url!r}, got {url!r}'
            )

    for target, expected_parts in SPLIT_CASES:
        parts = split_targets(target)
        if parts != expected_parts:
            failures.append(
                f'  split_targets("{target}")\n      expected {expected_parts!r}, got {parts!r}'
            )

    total = len(CASES) + len(RESOLVE_CASES) + len(SPLIT_CASES)
    if failures:
        print(f"FAILED  {len(failures)} of {total} checks\n")
        print("\n".join(failures))
        return 1

    print(f"PASSED  all {total} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
