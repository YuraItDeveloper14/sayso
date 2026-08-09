"""Intent parser tests. No audio, no model, no browser - run them anywhere:

    python tests/test_intents.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sayso.intents import parse, resolve_target  # noqa: E402

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

    # -- nonsense should stay inert ---------------------------------------
    ("", "unknown", {}),
    ("uh yeah so anyway", "unknown", {}),
]

RESOLVE_CASES = [
    ("youtube", "https://www.youtube.com"),
    ("you tube", "https://www.youtube.com"),
    ("the github website", "https://github.com"),
    ("github.com", "https://github.com"),
    ("example.org", "https://example.org"),
    ("notion", "https://www.notion.so"),
    ("figma", "https://www.figma.com"),
    ("someunknownapp", "https://someunknownapp.com"),
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

    total = len(CASES) + len(RESOLVE_CASES)
    if failures:
        print(f"FAILED  {len(failures)} of {total} checks\n")
        print("\n".join(failures))
        return 1

    print(f"PASSED  all {total} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
