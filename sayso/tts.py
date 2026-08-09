"""The voice Sayso answers in.

Two engines, both offline. Piper is a small neural voice that runs on the CPU
and sounds like a person; Windows SAPI5 is the robot that is already installed.
Piper is used when its model is on disk, SAPI5 is the fallback, and neither
needs an account or a key.

All speech goes through one worker thread. Playback opens its own output stream
rather than using sounddevice's shared one, for the same reason the alarm does:
touching that stream from another thread takes PortAudio down at the C level.
"""

import queue
import threading

import numpy as np
import sounddevice as sd

from .config import ROOT, settings

PIPER_DIR = ROOT / "models" / "piper"
CHUNK = 1024


def piper_model_path():
    """The first Piper voice found, or None."""
    if not PIPER_DIR.is_dir():
        return None
    models = sorted(PIPER_DIR.glob("*.onnx"))
    return models[0] if models else None


class Speaker:
    def __init__(self, enabled=True, rate=185):
        self.enabled = enabled
        self.rate = rate
        self._queue = queue.Queue()
        self._voice = None
        self._voice_tried = False
        self.engine = "starting"
        self.last_error = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="sayso-tts")
        self._thread.start()

    # ---------------------------------------------------------------- piper

    def _load_piper(self):
        """Load the neural voice once, on the speech thread."""
        if self._voice_tried:
            return self._voice
        self._voice_tried = True

        if settings.voice_engine == "sapi":
            self.engine = "sapi5"
            return None

        path = piper_model_path()
        if path is None:
            self.engine = "sapi5"
            return None

        try:
            from piper import PiperVoice

            self._voice = PiperVoice.load(str(path))
            self.engine = f"piper ({path.stem})"
        except Exception as exc:
            self.last_error = f"piper unavailable: {exc}"
            self.engine = "sapi5"
        return self._voice

    def _say_piper(self, text):
        voice = self._voice
        stream = None
        try:
            for chunk in voice.synthesize(text):
                samples = chunk.audio_float_array
                if stream is None:
                    stream = sd.OutputStream(
                        samplerate=chunk.sample_rate,
                        channels=chunk.sample_channels,
                        dtype="float32",
                    )
                    stream.start()
                for start in range(0, len(samples), CHUNK):
                    stream.write(np.ascontiguousarray(samples[start:start + CHUNK]))
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False
        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    # ----------------------------------------------------------------- sapi

    def _say_sapi(self, text):
        try:
            import pyttsx3

            # A fresh engine per utterance: pyttsx3 keeps global state and
            # deadlocks if a long-lived one is driven repeatedly on Windows.
            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as exc:
            # No voice installed, or SAPI is busy. Speech is a nicety; the
            # dashboard still shows every reply as text.
            self.last_error = str(exc)

    # --------------------------------------------------------------- worker

    def _run(self):
        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                voice = self._load_piper()
                if voice is None or not self._say_piper(text):
                    self._say_sapi(text)
            finally:
                self._queue.task_done()

    def say(self, text):
        if self.enabled and text:
            self._queue.put(text)

    def wait(self):
        self._queue.join()


speaker = Speaker()
