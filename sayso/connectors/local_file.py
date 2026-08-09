"""Append notes to a Markdown file.

This is the Obsidian connector. Obsidian has no API and needs no token - a
vault is a folder of Markdown files, so pointing this at a note inside one puts
captured thoughts straight into the vault. It works with the network off, which
no hosted connector can claim.

Also works for Logseq, Foam, or any plain-text notes system.
"""

import time
from pathlib import Path

from .base import Connector, Delivery


class LocalFileConnector(Connector):
    type_name = "local file"

    @property
    def path(self):
        raw = (self.config.get("path") or "").strip()
        return Path(raw).expanduser() if raw else None

    @property
    def is_configured(self):
        path = self.path
        return path is not None and path.parent.is_dir()

    @property
    def needs(self):
        raw = (self.config.get("path") or "").strip()
        if not raw:
            return "choose a file to append to"
        if not self.path.parent.is_dir():
            return f"folder does not exist: {self.path.parent}"
        return ""

    def send_note(self, text):
        path = self.path
        if path is None:
            return Delivery(False, "no path configured")

        template = self.config.get("format", "- [ ] {text}")
        line = template.format(text=text, time=time.strftime("%H:%M"), date=time.strftime("%Y-%m-%d"))

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            # Keep the file tidy whether or not it already ended in a newline.
            separator = "" if not existing or existing.endswith("\n") else "\n"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(f"{separator}{line}\n")
            self.last_error = ""
            return Delivery(True, str(path))
        except OSError as exc:
            self.last_error = str(exc)
            return Delivery(False, str(exc))

    def describe(self):
        info = super().describe()
        info["fields"] = [
            {"key": "path", "label": "File to append to", "value": self.config.get("path", ""),
             "placeholder": r"C:\Users\you\Vault\Inbox.md"},
            {"key": "format", "label": "Line format", "value": self.config.get("format", ""),
             "placeholder": "- [ ] {text}"},
        ]
        return info
