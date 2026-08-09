"""Timers and reminders.

One background thread sleeps until the nearest deadline instead of polling, so
an idle timer costs nothing. Timers are written to disk, so closing the app and
reopening it does not lose the one you set five minutes ago.
"""

import json
import threading
import time

from .config import DATA_DIR

TIMERS_FILE = DATA_DIR / "timers.json"


def humanize(seconds):
    """Seconds to something worth reading aloud."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        if rest and minutes < 10:
            return f"{minutes} minute{'s' if minutes != 1 else ''} {rest} seconds"
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, minutes = divmod(minutes, 60)
    if minutes:
        return f"{hours} hour{'s' if hours != 1 else ''} {minutes} minutes"
    return f"{hours} hour{'s' if hours != 1 else ''}"


class TimerScheduler:
    def __init__(self, path=TIMERS_FILE):
        self._path = path
        self._condition = threading.Condition()
        self._timers = []
        self._on_fire = None
        self._next_id = 1
        self._load()
        self._thread = threading.Thread(target=self._run, daemon=True, name="stayso-timers")
        self._thread.start()

    # -------------------------------------------------------------- storage

    def _load(self):
        if not self._path.exists():
            return
        try:
            stored = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        # A reminder whose moment passed while the app was closed is dropped
        # rather than announced late: nobody wants six alarms at once on
        # startup, and a reminder for a moment that is gone is just noise.
        now = time.time()
        self._timers = [t for t in stored if t["at"] > now]
        self._next_id = max((t["id"] for t in stored), default=0) + 1

    def _write(self):
        self._path.write_text(
            json.dumps(self._timers, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------- schedule

    def set_callback(self, callback):
        self._on_fire = callback

    def add(self, seconds, label):
        timer = {
            "id": self._next_id,
            "label": label.strip() or "timer",
            "at": time.time() + seconds,
            "seconds": seconds,
        }
        with self._condition:
            self._next_id += 1
            self._timers.append(timer)
            self._write()
            self._condition.notify_all()
        return timer

    def cancel(self, timer_id):
        with self._condition:
            for i, timer in enumerate(self._timers):
                if timer["id"] == timer_id:
                    removed = self._timers.pop(i)
                    self._write()
                    self._condition.notify_all()
                    return removed
        return None

    def cancel_all(self):
        with self._condition:
            count = len(self._timers)
            self._timers = []
            self._write()
            self._condition.notify_all()
        return count

    def active(self):
        now = time.time()
        with self._condition:
            timers = sorted(self._timers, key=lambda t: t["at"])
        return [{**t, "remaining": max(0, t["at"] - now)} for t in timers]

    # ----------------------------------------------------------------- loop

    def _run(self):
        while True:
            with self._condition:
                while not self._timers:
                    self._condition.wait()

                nearest = min(self._timers, key=lambda t: t["at"])
                delay = nearest["at"] - time.time()
                if delay > 0:
                    # A new, sooner timer wakes this early via notify_all.
                    self._condition.wait(timeout=delay)
                    continue

                self._timers.remove(nearest)
                self._write()

            # Fire outside the lock so a slow callback cannot stall scheduling.
            if self._on_fire is not None:
                try:
                    self._on_fire(nearest)
                except Exception:
                    pass


scheduler = TimerScheduler()
