"""POST each note to a URL.

The escape hatch: anything with an inbound webhook - Zapier, Make, n8n, IFTTT,
a Discord channel, your own server - accepts notes without needing a dedicated
connector written for it.
"""

import time

from .base import Connector, Delivery


class WebhookConnector(Connector):
    type_name = "webhook"
    requires_network = True

    @property
    def url(self):
        return (self.config.get("url") or "").strip()

    @property
    def is_configured(self):
        return self.url.startswith("http://") or self.url.startswith("https://")

    @property
    def needs(self):
        if not self.url:
            return "add the URL to post to"
        if not self.is_configured:
            return "URL must start with http:// or https://"
        return ""

    def send_note(self, text):
        if not self.is_configured:
            return Delivery(False, "no URL configured")

        import requests

        payload = {"text": text, "source": "sayso", "at": time.time()}
        payload.update(self.config.get("extra_fields") or {})

        try:
            response = requests.post(
                self.url,
                json=payload,
                headers=self.config.get("headers") or {},
                timeout=float(self.config.get("timeout", 6)),
            )
            if response.status_code >= 400:
                self.last_error = f"HTTP {response.status_code}"
                return Delivery(False, self.last_error)
            self.last_error = ""
            return Delivery(True, f"HTTP {response.status_code}")
        except Exception as exc:
            self.last_error = str(exc)
            return Delivery(False, str(exc))

    def describe(self):
        info = super().describe()
        info["fields"] = [
            {"key": "url", "label": "Post to", "value": self.url,
             "placeholder": "https://hooks.example.com/..."},
        ]
        return info
