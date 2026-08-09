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
    r"^(?:(?:hey|ok|okay|yo)\s+)?(?:sayso|computer)?[,\s]*(?:um+|uh+|er+|so|please)?[,\s]*",
    re.IGNORECASE,
)

NOTE_WORDS = r"(?:notes?|lists?|tasks?|to-?dos?|reminders?|agenda)"
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}


@dataclass
class Intent:
    name: str
    params: dict = field(default_factory=dict)
    raw: str = ""
    normalized: str = ""

    @property
    def understood(self):
        return self.name != "unknown"


def normalize(text):
    """Lowercase, de-punctuate, and repair common mis-hearings."""
    cleaned = text.strip().lower()
    cleaned = LEADING_NOISE.sub("", cleaned, count=1)
    for pattern, replacement in SPOKEN_FIXES:
        cleaned = re.sub(pattern, replacement, cleaned)
    cleaned = re.sub(r"[?!.]+$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def resolve_target(raw_target):
    """Map a spoken destination to (label, url).

    Known alias wins; then anything that looks like a domain; then a bare word
    is optimistically treated as `<word>.com`; anything longer is a search.
    """
    target = raw_target.strip().strip(".,")
    target = re.sub(r"^(?:the|my|a)\s+", "", target)
    target = re.sub(r"\s+(?:website|site|page|app|dot com)$", "", target)
    target = re.sub(r"^www\.", "", target)

    if target in SITES:
        return SITES[target]

    collapsed = target.replace(" ", "")
    if collapsed in SITES:
        return SITES[collapsed]

    if re.fullmatch(r"[a-z0-9-]+\.[a-z]{2,}(?:/\S*)?", target):
        label = target.split("/")[0]
        return (label, f"https://{target}")

    if " " not in target and len(target) > 1:
        return (target.capitalize(), f"https://{target}.com")

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
        return Intent("unknown", {"reason": "empty"}, raw=text, normalized=normalized)

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
