"""Settings for StaySo, persisted to data/settings.json."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

NOTES_FILE = DATA_DIR / "notes.json"
HISTORY_FILE = DATA_DIR / "history.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS = {
    # Measured on this 4-core / 6 GB laptop, average per spoken command:
    #   tiny.en   ~1.7-2.2 s   (all test commands parsed correctly)
    #   base.en   ~3.4 s       (same accuracy, twice the wait)
    #   small.en  ~25-30 s     (unusable here)
    # tiny.en wins for short commands. Switch to base.en if you dictate long
    # notes and want the extra accuracy more than the speed.
    "model_size": "tiny.en",
    "language": "en",
    "sample_rate": 16000,
    # Anything shorter than this is a stray keypress, not a command.
    "min_recording_seconds": 0.35,
    "max_recording_seconds": 30.0,
    "hotkey_modifiers": ["ctrl", "alt"],
    "hotkey_key": "s",
    "speak_replies": True,
    # "auto" uses the Piper neural voice when its model is in models/piper,
    # and falls back to the Windows SAPI5 robot. "sapi" forces the fallback.
    "voice_engine": "auto",
    # Short blips on key down and key up. The app runs in the background, so
    # without them you have no confirmation it is listening.
    "click_sounds": True,
    # A timer that comes due keeps ringing until it is dismissed.
    "alarm_sound": True,
    # Pause between opening Google and opening the destination, so the
    # "through Google" route is actually visible on screen.
    "google_hop_delay": 1.2,
    # When the offline grammar does not recognise a command, optionally ask a
    # model to map it to one of the commands that already exist. Needs a key in
    # data/keys.json or the OPENROUTER_API_KEY environment variable, and needs
    # the network. Off without one.
    "use_llm_fallback": True,
    "llm_model": "openai/gpt-4o-mini",
    "web_port": 5000,
    "open_browser_on_start": True,
}


class Settings:
    """Dict-backed settings with attribute access and JSON persistence."""

    def __init__(self, values=None):
        self._values = dict(DEFAULTS)
        if values:
            self._values.update(values)

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def as_dict(self):
        return dict(self._values)

    @property
    def hotkey_label(self):
        parts = [m.capitalize() for m in self._values["hotkey_modifiers"]]
        parts.append(self._values["hotkey_key"].upper())
        return "+".join(parts)

    @classmethod
    def load(cls):
        if SETTINGS_FILE.exists():
            try:
                return cls(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
        return cls()

    def save(self):
        SETTINGS_FILE.write_text(
            json.dumps(self._values, indent=2), encoding="utf-8"
        )


settings = Settings.load()
