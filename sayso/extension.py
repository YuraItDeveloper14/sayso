"""Bridge to the browser extension.

The daemon cannot close a tab or scroll a page - nothing outside the browser
can. Those commands are published on the same event stream the dashboard uses,
and the extension picks them up.

The extension checks in every few seconds so the daemon knows whether anyone is
listening. Without that, "close tab" would appear to succeed and quietly do
nothing.
"""

import time

from .events import bus

STALE_AFTER = 25  # seconds without a check-in before we call it disconnected


class ExtensionBridge:
    def __init__(self):
        self.last_seen = 0.0
        self.browser = ""

    def ping(self, browser=""):
        self.last_seen = time.time()
        if browser:
            self.browser = browser

    @property
    def connected(self):
        return (time.time() - self.last_seen) < STALE_AFTER

    def send(self, action):
        if not self.connected:
            return False
        bus.publish("browser_action", action=action)
        return True

    def describe(self):
        return {
            "connected": self.connected,
            "browser": self.browser,
            "last_seen": self.last_seen,
        }


bridge = ExtensionBridge()
