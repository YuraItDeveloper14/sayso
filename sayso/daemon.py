"""The daemon: hotkey in, action out.

Three threads matter here. pynput's listener thread must never block, so it only
starts and stops the recorder. A single worker thread does transcription and
execution, which also serialises Whisper. Flask runs the dashboard separately.
"""

import queue
import threading
import time

from . import actions, events, intents
from .audio import MicUnavailable, Recorder
from .config import settings
from .events import bus
from .history import history
from .hotkey import PushToTalk
from .stt import transcriber
from .timers import scheduler
from .tts import speaker

# Which intents change which panel, so the dashboard refreshes only what moved.
REFRESH_EVENTS = {
    "write_note": "notes_changed",
    "read_notes": "notes_changed",
    "complete_note": "notes_changed",
    "delete_note": "notes_changed",
    "clear_notes": "notes_changed",
    "set_timer": "timers_changed",
    "cancel_timers": "timers_changed",
    "teach_alias": "aliases_changed",
    "forget_alias": "aliases_changed",
}


class SaysoDaemon:
    def __init__(self):
        self.recorder = Recorder()
        self.hotkey = PushToTalk(
            settings.hotkey_modifiers,
            settings.hotkey_key,
            on_start=self._on_hold_start,
            on_stop=self._on_hold_stop,
        )
        self._jobs = queue.Queue()
        self._worker = threading.Thread(
            target=self._work, daemon=True, name="sayso-worker"
        )
        self._started = False
        self.model_ready = False

    # ------------------------------------------------------------------ setup

    def start(self):
        if self._started:
            return
        self._started = True
        self._worker.start()
        scheduler.set_callback(self._on_timer)
        threading.Thread(target=self._load_model, daemon=True, name="sayso-load").start()
        self.hotkey.start()

    def _on_timer(self, timer):
        """A reminder came due. Say it out loud and show it on the dashboard."""
        spoken = f"Reminder: {timer['label']}"
        bus.publish("timer_fired", timer=timer)
        bus.publish("timers_changed")
        if settings.speak_replies:
            speaker.say(spoken)

    def _load_model(self):
        bus.set_status(events.LOADING, f"loading {settings.model_size}")
        started = time.time()
        try:
            transcriber.load()
            self.model_ready = True
            bus.set_status(events.IDLE, "ready")
            bus.publish(
                "log",
                level="info",
                message=f"Model {settings.model_size} ready in {time.time() - started:.1f}s",
            )
        except Exception as exc:
            bus.set_status(events.ERROR, "model failed to load")
            bus.publish("log", level="error", message=f"Model load failed: {exc}")

    # ----------------------------------------------------------------- hotkey

    def _on_hold_start(self):
        try:
            self.recorder.start()
        except MicUnavailable as exc:
            bus.set_status(events.ERROR, "microphone unavailable")
            bus.publish("log", level="error", message=f"Microphone error: {exc}")
            return
        detail = "listening" if self.model_ready else "listening (model still loading)"
        bus.set_status(events.LISTENING, detail)

    def _on_hold_stop(self):
        audio = self.recorder.stop()
        if audio is None:
            bus.set_status(events.IDLE, "too short, ignored")
            return
        bus.set_status(events.TRANSCRIBING, "transcribing")
        self._jobs.put(("audio", audio, time.time()))

    # ----------------------------------------------------------------- worker

    def _work(self):
        while True:
            kind, payload, started = self._jobs.get()
            try:
                if kind == "audio":
                    self._process_audio(payload, started)
                else:
                    self._process_text(payload, started, source="web")
            except Exception as exc:
                bus.set_status(events.ERROR, str(exc))
                bus.publish("log", level="error", message=f"Worker error: {exc}")
            finally:
                self._jobs.task_done()

    def _process_audio(self, audio, started):
        text = transcriber.transcribe(audio)
        bus.publish("transcript", text=text, source="voice")
        if not text:
            bus.set_status(events.IDLE, "nothing heard")
            return
        self._dispatch(text, started, source="voice")

    def _process_text(self, text, started, source):
        bus.publish("transcript", text=text, source=source)
        self._dispatch(text, started, source=source)

    def _dispatch(self, text, started, source):
        bus.set_status(events.EXECUTING, "running command")
        intent = intents.parse(text)
        # So a note remembers whether it was spoken or typed.
        intent.params.setdefault("source", source)
        result = actions.execute(intent)

        entry = history.add(
            transcript=text,
            intent=intent.name,
            result=result,
            source=source,
            latency=time.time() - started,
        )
        bus.publish("command", entry=entry)
        refresh = REFRESH_EVENTS.get(intent.name)
        if refresh:
            bus.publish(refresh)

        if settings.speak_replies and result.say:
            speaker.say(result.say)

        bus.set_status(events.IDLE, "ready")
        return result

    # ------------------------------------------------------------- public API

    def submit_text(self, text):
        """Run a typed command - used by the dashboard's text box."""
        self._jobs.put(("text", text, time.time()))


daemon = SaysoDaemon()
