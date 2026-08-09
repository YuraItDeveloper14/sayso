"""Turn a transcribed sentence into a structured intent.

Deliberately rule-based rather than an LLM call: it runs offline, answers in
under a millisecond, and never invents an action that was not asked for.
"""

import re
from dataclasses import dataclass, field

# Sites worth naming out loud. Anything not listed still resolves - see
# `resolve_target` - this just makes the common cases exact.
SITES = {
    "youtube": ("YouTube", "https://www.youtube.com"),
    "google": ("Google", "https://www.google.com"),
    "gmail": ("Gmail", "https://mail.google.com"),
    "email": ("Gmail", "https://mail.google.com"),
    "inbox": ("Gmail", "https://mail.google.com"),
    "github": ("GitHub", "https://github.com"),
    "reddit": ("Reddit", "https://www.reddit.com"),
    "wikipedia": ("Wikipedia", "https://en.wikipedia.org"),
    "twitter": ("X", "https://x.com"),
    "x": ("X", "https://x.com"),
    "instagram": ("Instagram", "https://www.instagram.com"),
    "facebook": ("Facebook", "https://www.facebook.com"),
    "linkedin": ("LinkedIn", "https://www.linkedin.com"),
    "discord": ("Discord", "https://discord.com/app"),
    "twitch": ("Twitch", "https://www.twitch.tv"),
    "spotify": ("Spotify", "https://open.spotify.com"),
    "netflix": ("Netflix", "https://www.netflix.com"),
    "amazon": ("Amazon", "https://www.amazon.com"),
    "chatgpt": ("ChatGPT", "https://chat.openai.com"),
    "claude": ("Claude", "https://claude.ai"),
    "stack overflow": ("Stack Overflow", "https://stackoverflow.com"),
    "stackoverflow": ("Stack Overflow", "https://stackoverflow.com"),
    "maps": ("Google Maps", "https://maps.google.com"),
    "translate": ("Google Translate", "https://translate.google.com"),
    "drive": ("Google Drive", "https://drive.google.com"),
    "docs": ("Google Docs", "https://docs.google.com"),
    "calendar": ("Google Calendar", "https://calendar.google.com"),
    "notion": ("Notion", "https://www.notion.so"),
    "figma": ("Figma", "https://www.figma.com"),
    "devpost": ("Devpost", "https://devpost.com"),
}

SEARCH_ENGINES = {
    "google": ("Google", "https://www.google.com/search?q={q}"),
    "youtube": ("YouTube", "https://www.youtube.com/results?search_query={q}"),
    "wikipedia": ("Wikipedia", "https://en.wikipedia.org/w/index.php?search={q}"),
    "reddit": ("Reddit", "https://www.reddit.com/search/?q={q}"),
    "github": ("GitHub", "https://github.com/search?q={q}"),
    "amazon": ("Amazon", "https://www.amazon.com/s?k={q}"),
    "stack overflow": ("Stack Overflow", "https://stackoverflow.com/search?q={q}"),
}

# Whisper hears these as two words often enough to be worth fixing up front.
SPOKEN_FIXES = [
    (r"\byou tube\b", "youtube"),
    (r"\bgit hub\b", "github"),
    (r"\bg mail\b", "gmail"),
    (r"\bwiki pedia\b", "wikipedia"),
    (r"\bchat gpt\b", "chatgpt"),
    (r"\bstack overflow\b", "stack overflow"),
    (r"\bdot com\b", ".com"),
    (r"\bdot org\b", ".org"),
    (r"\bdot io\b", ".io"),
    (r"\bdot net\b", ".net"),
    (r"\bto-do\b", "todo"),
    (r"\bto do list\b", "todo list"),
]

# Wake words and filler Whisper faithfully transcribes but we do not want.
LEADING_NOISE = re.compile(
    r"^(?:(?:hey|ok|okay|yo)\s+)?(?:stayso|computer)?[,\s]*(?:um+|uh+|er+|so|please)?[,\s]*",
    re.IGNORECASE,
)

NOTE_WORDS = r"(?:notes?|lists?|tasks?|to-?dos?|reminders?|agenda)"
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}

# Whisper writes most numbers as digits, but not always, and "a minute" is how
# people actually talk.
NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "sixty": 60,
    "half a": 0.5, "half an": 0.5, "a couple of": 2, "couple of": 2,
}
AMOUNT = r"\d+|half an|half a|a couple of|couple of|forty five|" + "|".join(
    sorted((w for w in NUMBER_WORDS if " " not in w), key=len, reverse=True)
)
UNIT_SECONDS = {"sec": 1, "second": 1, "min": 60, "minute": 60, "hour": 3600}
UNITS = r"sec|second|min|minute|hour"


def parse_duration(amount, unit):
    """('20', 'minute') -> 1200 seconds."""
    amount = amount.strip().lower()
    value = float(amount) if amount.isdigit() else NUMBER_WORDS.get(amount, 1)
    return int(value * UNIT_SECONDS[unit.strip().lower().rstrip("s")])


@dataclass
class Intent:
    name: str
    params: dict = field(default_factory=dict)
    raw: str = ""
    normalized: str = ""

    @property
    def understood(self):
        return self.name != "unknown"


# Whisper does not return "I heard nothing" - it returns its best guess at what
# a cough or a scrape of the desk might have been. These are the shapes that
# guess takes, and echoing them back as a failed command makes StaySo look
# broken when the truth is that nothing was said.
HALLUCINATIONS = {
    "you", "thank you", "thanks", "thanks for watching", "bye", "ok", "okay",
    "thank you for watching", "please subscribe", "the end", "hmm", "uh",
    "so", "yeah", "mm", "mhm", "oh",
}


def looks_like_noise(text):
    """True when the transcript is a misheard noise rather than speech."""
    cleaned = re.sub(r"[^\w\s']", "", text.lower()).strip()
    if not cleaned:
        return True
    if cleaned in HALLUCINATIONS:
        return True

    words = cleaned.split()
    letters = re.sub(r"[^a-z]", "", cleaned)
    if len(letters) < 2:
        return True

    # A stutter loop - "luringy, luringy, luringy" - is the model latching onto
    # a sound and repeating it. Real commands do not stammer.
    if len(words) >= 3:
        longest_run = run = 1
        for previous, current in zip(words, words[1:]):
            run = run + 1 if current == previous else 1
            longest_run = max(longest_run, run)
        if longest_run >= 3:
            return True
        if len(set(words)) == 1:
            return True
        # Three or more repeats of any single word in a short utterance.
        if len(words) <= 12 and max(words.count(w) for w in set(words)) >= 3:
            return True

    return False


def split_targets(target):
    """"notion and github" -> ["notion", "github"], for multi-step shortcuts."""
    parts = re.split(r"\s*(?:,|\band then\b|\band\b|\bplus\b)\s*", target, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def normalize(text):
    """Lowercase, de-punctuate, and repair common mis-hearings."""
    cleaned = text.strip().lower()
    cleaned = LEADING_NOISE.sub("", cleaned, count=1)
    for pattern, replacement in SPOKEN_FIXES:
        cleaned = re.sub(pattern, replacement, cleaned)
    cleaned = re.sub(r"[?!.]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def resolve_target(raw_target, _following_alias=False):
    """Map a spoken destination to (label, url).

    Phrases you taught win first, then the built-in list, then anything that
    looks like a URL or a domain; a bare word is optimistically treated as
    `<word>.com`; anything longer is a search.
    """
    target = raw_target.strip().strip(".,")
    target = re.sub(r"^(?:the|my|a)\s+", "", target)
    target = re.sub(r"\s+(?:website|site|page|app|dot com)$", "", target)

    if target.startswith(("http://", "https://")):
        label = target.split("//", 1)[1].split("/")[0]
        return (label, target)

    if not _following_alias:
        from .aliases import store as alias_store

        taught = alias_store.lookup(target)
        if taught:
            label, url = resolve_target(taught, _following_alias=True)
            return (label or target, url)

    target = re.sub(r"^www\.", "", target)

    if target in SITES:
        return SITES[target]

    collapsed = target.replace(" ", "")
    if collapsed in SITES:
        return SITES[collapsed]

    if re.fullmatch(r"[a-z0-9-]+\.[a-z]{2,}(?:/\S*)?", target):
        label = target.split("/")[0]
        return (label, f"https://{target}")

    # A bare unknown word used to become "<word>.com", which is right for
    # "hackerrank" and nonsense for "notepad". A search is never wrong, only
    # one click longer, so unknown words fall through to one.
    return (None, None)


def _search_url(engine, query):
    from urllib.parse import quote_plus

    label, template = SEARCH_ENGINES.get(engine, SEARCH_ENGINES["google"])
    return label, template.format(q=quote_plus(query))


def _position(token):
    token = token.strip().lower()
    if token == "last":
        return "last"
    if token in ORDINALS:
        return ORDINALS[token]
    return int(token)


# Rules are tried top to bottom, so the specific ones come first.
RULES = []


def rule(name, pattern):
    compiled = re.compile(pattern, re.IGNORECASE)

    def decorator(builder):
        RULES.append((name, compiled, builder))
        return builder

    return decorator


# Timers come before notes: "remind me in ten minutes" and "remind me to call
# mum" start identically, and only the next word tells them apart.


@rule("set_timer", rf"^remind me in (?P<amount>{AMOUNT}) (?P<unit>{UNITS})s?,? (?:to |that )?(?P<label>.+)$")
@rule("set_timer", rf"^in (?P<amount>{AMOUNT}) (?P<unit>{UNITS})s?,? remind me (?:to )?(?P<label>.+)$")
def _set_timer_labelled(match, text):
    return Intent(
        "set_timer",
        {
            "seconds": parse_duration(match.group("amount"), match.group("unit")),
            "label": match.group("label").strip(),
        },
    )


@rule(
    "set_timer",
    rf"^(?:set|start) (?:a |an )?(?:timer|alarm) for (?P<amount>{AMOUNT}) (?P<unit>{UNITS})s?"
    r"(?:,? (?:to|for|called) (?P<label>.+))?$",
)
@rule(
    "set_timer",
    rf"^(?:start a )?(?P<amount>{AMOUNT}) (?P<unit>{UNITS})s? timer"
    r"(?:,? (?:to|for|called) (?P<label>.+))?$",
)
def _set_timer(match, text):
    return Intent(
        "set_timer",
        {
            "seconds": parse_duration(match.group("amount"), match.group("unit")),
            "label": (match.group("label") or "").strip(),
        },
    )


@rule("cancel_timers", r"^(?:cancel|stop|clear)\s+(?:all\s+)?(?:my\s+)?(?:the\s+)?timers?$")
def _cancel_timers(match, text):
    return Intent("cancel_timers")


@rule("list_timers", r"^(?:what|which)\s+timers?\b.*$")
@rule("list_timers", r"^(?:list|show)\s+(?:me\s+)?(?:my\s+)?timers?$")
def _list_timers(match, text):
    return Intent("list_timers")


# Teaching a phrase must also outrank note-writing, so that "remember standup as
# <url>" is a shortcut and not a note about a URL.


@rule("teach_alias", r"^when i say (?P<phrase>.+?),? (?:open|go to|launch|that means) (?P<target>.+)$")
@rule("teach_alias", r"^(?:teach|learn) (?:that )?(?P<phrase>.+?) (?:is|means|opens) (?P<target>.+)$")
@rule("teach_alias", r"^(?:remember|save) (?P<phrase>.+?) as (?P<target>.+)$")
def _teach_alias(match, text):
    return Intent(
        "teach_alias",
        {"phrase": match.group("phrase").strip(), "target": match.group("target").strip()},
    )


@rule("forget_alias", r"^forget (?:the )?(?:shortcut )?(?P<phrase>.+)$")
def _forget_alias(match, text):
    return Intent("forget_alias", {"phrase": match.group("phrase").strip()})


# Listing shortcuts out loud is gone: you set them up looking at the screen,
# and the Shortcuts panel is already showing them. Two fewer rules that could
# swallow something else.
#
# Listing *timers* stays, though I argued for cutting both. Timers are the one
# thing you ask about precisely when you cannot see the screen - the app is
# running in the background, which is the whole point of it.


# Recovery, and silencing a ringing alarm. Both are short phrases people say
# reflexively, so they are matched before anything can claim them.


@rule("undo", r"^(?:undo(?: that| it| the last one)?|scratch that|take that back|cancel that)$")
def _undo(match, text):
    return Intent("undo")


# "ok" and "got it" used to be here and were a mistake: they are things people
# say for a hundred reasons, and one of them should not silently swallow a
# command. Only words whose sole purpose is stopping a noise remain.
@rule("dismiss_alarm", r"^(?:stop|dismiss|enough|quiet|silence|shut up|turn it off)$")
def _dismiss_alarm(match, text):
    return Intent("dismiss_alarm")


# Tab control. The daemon cannot do any of this itself - it is handed to the
# browser extension, which is why these fail loudly when nothing is connected.


@rule("browser", r"^close (?:the |this )?tab$")
def _close_tab(match, text):
    return Intent("browser", {"action": "close_tab"})


@rule("browser", r"^(?:open (?:a )?)?new tab$")
def _new_tab(match, text):
    return Intent("browser", {"action": "new_tab"})


@rule("browser", r"^reopen (?:the )?(?:last )?(?:closed )?tab$")
def _reopen_tab(match, text):
    return Intent("browser", {"action": "reopen_tab"})


@rule("browser", r"^(?:go to (?:the )?)?next tab$")
def _next_tab(match, text):
    return Intent("browser", {"action": "next_tab"})


@rule("browser", r"^(?:go to (?:the )?)?(?:previous|last) tab$")
def _previous_tab(match, text):
    return Intent("browser", {"action": "previous_tab"})


@rule("browser", r"^(?:reload|refresh)(?: (?:the|this) page)?$")
def _reload(match, text):
    return Intent("browser", {"action": "reload"})


@rule("browser", r"^scroll (?:to the )?(?P<where>up|down|top|bottom)$")
@rule("browser", r"^(?:go to (?:the )?)?(?P<where>top|bottom) of (?:the )?page$")
def _scroll(match, text):
    return Intent("browser", {"action": f"scroll_{match.group('where')}"})


@rule("read_notes", rf"^(?:read|read out|read back|say|recite)\b.*\b{NOTE_WORDS}\b")
@rule("read_notes", rf"^(?:what(?:'s| is| are)?|tell me|show me|list)\b.*\b{NOTE_WORDS}\b")
@rule("read_notes", r"^what do i have\b.*$")
@rule("read_notes", r"^what(?:'s| is) on my (?:plate|schedule)\b")
@rule("read_notes", rf"^(?:open|show)\s+(?:my\s+)?{NOTE_WORDS}$")
def _read_notes(match, text):
    return Intent("read_notes")


@rule("clear_notes", rf"^(?:clear|delete|remove|wipe|erase)\s+(?:all\s+)?(?:of\s+)?(?:my\s+)?{NOTE_WORDS}$")
def _clear_notes(match, text):
    return Intent("clear_notes")


@rule(
    "complete_note",
    r"^(?:done with|complete|completed|check off|tick off|mark(?: off)?|finish(?:ed)?)"
    r"\s+(?:the\s+)?(?:note\s+|task\s+|item\s+)?(?:number\s+)?(?P<pos>\d+|first|second|third|fourth|fifth|last)\b",
)
def _complete_note(match, text):
    return Intent("complete_note", {"position": _position(match.group("pos"))})


@rule(
    "delete_note",
    r"^(?:delete|remove|drop)\s+(?:the\s+)?(?:note\s+|task\s+|item\s+)?(?:number\s+)?"
    r"(?P<pos>\d+|first|second|third|fourth|fifth|last)\b",
)
def _delete_note(match, text):
    return Intent("delete_note", {"position": _position(match.group("pos"))})


@rule(
    "write_note",
    r"^(?:note|new note|take (?:a |down )?note|make a note|note down|write (?:down|a note)"
    r"|jot (?:down|this down)|add (?:a )?(?:note|task|to-?do|reminder)|remind me (?:to|that)"
    r"|remember (?:to|that)|save (?:a )?note)\b[:,]?\s+(?P<body>.+)$",
)
def _write_note(match, text):
    return Intent("write_note", {"text": match.group("body").strip()})


@rule(
    "site_search",
    r"^(?:search(?: for)?|find|look up|look for)\s+(?P<query>.+?)\s+(?:on|in)\s+"
    r"(?P<engine>youtube|google|wikipedia|reddit|github|amazon|stack overflow)$",
)
def _site_search(match, text):
    return Intent(
        "site_search",
        {"query": match.group("query").strip(), "engine": match.group("engine").lower()},
    )


@rule(
    "site_search",
    r"^(?P<engine>youtube|google|wikipedia|reddit|github|amazon)\s+search\s+"
    r"(?:for\s+)?(?P<query>.+)$",
)
def _site_search_prefix(match, text):
    return Intent(
        "site_search",
        {"query": match.group("query").strip(), "engine": match.group("engine").lower()},
    )


@rule(
    "open_via_google",
    r"^(?:open(?: up)?|go to|launch|pull up|take me to|bring up)\s+(?P<target>.+?)\s+"
    r"(?:through|via|using|with|from|by way of)\s+google$",
)
def _open_via_google(match, text):
    return Intent("open_via_google", {"target": match.group("target").strip()})


@rule("search", r"^(?:google|search for|search|look up|look for|find me|find)\s+(?P<query>.+)$")
def _search(match, text):
    return Intent("search", {"query": match.group("query").strip()})


@rule(
    "open_site",
    r"^(?:open(?: up)?|go to|launch|pull up|take me to|bring up|start)\s+(?P<target>.+)$",
)
def _open_site(match, text):
    return Intent("open_site", {"target": match.group("target").strip()})


def parse(text):
    """Parse raw transcribed speech into an Intent."""
    normalized = normalize(text)
    if not normalized:
        return Intent("noise", {"reason": "empty"}, raw=text, normalized=normalized)

    # Separated from "unknown" on purpose. "I did not catch that" and "that is
    # not a command I know" are different messages, and only the second one is
    # worth showing the user what was heard.
    if looks_like_noise(normalized):
        return Intent("noise", {"reason": "noise"}, raw=text, normalized=normalized)

    for name, pattern, builder in RULES:
        match = pattern.match(normalized)
        if match:
            intent = builder(match, normalized)
            intent.raw = text
            intent.normalized = normalized
            return intent

    # A bare site name on its own is unambiguous enough to act on.
    if normalized in SITES:
        return Intent(
            "open_site", {"target": normalized}, raw=text, normalized=normalized
        )

    return Intent(
        "unknown", {"reason": "no_match"}, raw=text, normalized=normalized
    )
