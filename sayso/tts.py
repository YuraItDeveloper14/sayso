"""Offline text-to-speech through the Windows SAPI5 voices pyttsx3 wraps.

All speech goes through one worker thread. pyttsx3 keeps global state and
deadlocks if `runAndWait` is called from two threads, and on Windows a fresh
engine per utterance is more reliable than a long-lived one.
"""

import queue
import threading


class Speaker:
    def __init__(self, enabled=True, rate=185):
        self.enabled = enabled
        self.rate = rate
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="sayso-tts")
        self._thread.start()
        self.last_error = None

    def _run(self):
        while True:
            text = self._queue.get()
            if text is None:
                break
            try:
                import pyttsx3

                engine = pyttsx3.init()
                engine.setProperty("rate", self.rate)
                engine.say(text)
                engine.runAndWait()
                engine.stop()
            except Exception as exc:
                # No voice installed, or SAPI is busy. Speech is a nicety; the
                # dashboard still shows every reply as text.
                self.last_error = str(exc)
            finally:
                self._queue.task_done()

    def say(self, text):
        if self.enabled and text:
            self._queue.put(text)

    def wait(self):
        self._queue.join()


speaker = Speaker()
