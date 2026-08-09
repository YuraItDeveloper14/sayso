"""A tiny publish/subscribe bus so the web dashboard can watch the daemon live.

The daemon publishes; every connected browser holds one subscriber queue and
drains it over Server-Sent Events.
"""

import queue
import threading
import time
from collections import deque

# Daemon states surfaced to the UI.
IDLE = "idle"
LISTENING = "listening"
TRANSCRIBING = "transcribing"
EXECUTING = "executing"
LOADING = "loading"
ERROR = "error"


class EventBus:
    def __init__(self, history_size=100):
        self._subscribers = []
        self._lock = threading.Lock()
        self.recent = deque(maxlen=history_size)
        self.status = LOADING
        self.status_detail = "starting up"

    def publish(self, kind, **payload):
        event = {"kind": kind, "ts": time.time(), **payload}
        with self._lock:
            if kind == "status":
                self.status = payload.get("status", self.status)
                self.status_detail = payload.get("detail", "")
            else:
                self.recent.append(event)
            subscribers = list(self._subscribers)

        for q in subscribers:
            try:
                q.put_nowait(event)
            except queue.Full:
                # A browser tab that stopped draining; it will resync on reload.
                pass
        return event

    def set_status(self, status, detail=""):
        return self.publish("status", status=status, detail=detail)

    def subscribe(self):
        q = queue.Queue(maxsize=200)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def history(self):
        with self._lock:
            return list(self.recent)


bus = EventBus()
