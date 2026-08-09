"""Optional fallback: when the grammar does not recognise a command, ask a model.

The rule-based parser handles everything it was taught and answers in under a
millisecond offline. This is for the rest - "let's get to work", "I'm done for
today" - phrasings nobody wrote a rule for.

It only runs when the parser has already given up, so the offline path is never
slowed down or overruled, and it can only return an intent that already exists.
The model chooses between known commands; it cannot invent an action.

Off unless you add a key. See data/keys.json.
"""

import json
import os
import re

import requests

from .config import DATA_DIR, settings

KEYS_FILE = DATA_DIR / "keys.json"
ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT = 12

# What the model is allowed to answer with. Kept in step with actions.HANDLERS.
INTENT_MENU = """
open_site        {"target": "<site, app, folder or taught phrase>"}
open_via_google  {"target": "<site>"}
search           {"query": "<what to google>"}
site_search      {"query": "<what>", "engine": "youtube|google|wikipedia|reddit|github|amazon"}
write_note       {"text": "<the note>"}
read_notes       {}
complete_note    {"position": <number>}
delete_note      {"position": <number>}
clear_notes      {}
set_timer        {"seconds": <number>, "label": "<what for>"}
cancel_timers    {}
list_timers      {}
teach_alias      {"phrase": "<spoken phrase>", "target": "<where it goes>"}
forget_alias     {"phrase": "<spoken phrase>"}
list_aliases     {}
undo             {}
browser          {"action": "close_tab|new_tab|reopen_tab|next_tab|previous_tab|reload|scroll_up|scroll_down|scroll_top|scroll_bottom"}
"""

SYSTEM_PROMPT = f"""You map a spoken command to one of a fixed set of actions on \
the user's own laptop. Answer with JSON only, no prose, no code fences.

Available intents and their parameters:
{INTENT_MENU}
Answer shape: {{"intent": "<name>", "params": {{...}}}}

Rules:
- Choose only from the list above. Never invent an intent or a parameter.
- If the request does not clearly match one, answer {{"intent": "unknown", "params": {{}}}}.
- The transcript comes from speech recognition and may be slightly misheard. \
Correct obvious mishearings, but do not guess wildly.
- Prefer the least destructive reading. Never choose clear_notes or cancel_timers \
unless the user plainly asked to delete or cancel everything.
"""


def _read_keys():
    if KEYS_FILE.exists():
        try:
            return json.loads(KEYS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    # Written empty so there is an obvious place to paste a key into.
    try:
        KEYS_FILE.write_text(
            json.dumps({"openrouter": ""}, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
    return {}


class Interpreter:
    def __init__(self):
        self.last_error = ""

    @property
    def api_key(self):
        # Environment first, so a key never has to be written to disk at all.
        return os.environ.get("OPENROUTER_API_KEY") or _read_keys().get("openrouter", "")

    @property
    def available(self):
        return bool(settings.use_llm_fallback and self.api_key)

    def describe(self):
        return {
            "available": self.available,
            "enabled": bool(settings.use_llm_fallback),
            "has_key": bool(self.api_key),
            "model": settings.llm_model,
            "error": self.last_error,
        }

    def interpret(self, text):
        """Return (intent_name, params) or None. Never raises."""
        key = self.api_key
        if not key:
            return None

        try:
            response = requests.post(
                ENDPOINT,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "X-Title": "SaySo",
                },
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "max_tokens": 200,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": text},
                    ],
                },
                timeout=TIMEOUT,
            )
            if response.status_code >= 400:
                self.last_error = f"HTTP {response.status_code}"
                return None

            content = response.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            self.last_error = str(exc)
            return None

        # Models still wrap JSON in fences now and then.
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            self.last_error = "no JSON in reply"
            return None

        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            self.last_error = "reply was not valid JSON"
            return None

        name = parsed.get("intent")
        params = parsed.get("params") or {}
        if not name or name == "unknown" or not isinstance(params, dict):
            return None

        self.last_error = ""
        return name, params


interpreter = Interpreter()
