"""Connectors: mirror captured notes into the apps you actually use.

The local note store is always written first. Connectors run afterwards and are
allowed to fail - a dead token or an unplugged network never costs you a note.

Config lives in data/connectors.json, which is gitignored, so tokens stay on
the machine.
"""

import json
import threading

from ..config import DATA_DIR
from .local_file import LocalFileConnector
from .mcp_server import MCPConnector
from .webhook import WebhookConnector

CONNECTORS_FILE = DATA_DIR / "connectors.json"

TYPES = {
    "local_file": LocalFileConnector,
    "webhook": WebhookConnector,
    "mcp": MCPConnector,
}

# Starting points, all disabled until you fill them in. The command and env var
# for a hosted app come from that app's own MCP documentation - `docs` points
# at it. Check there before trusting the defaults below.
DEFAULT_CONFIG = {
    "obsidian": {
        "type": "local_file",
        "label": "Obsidian",
        "enabled": False,
        "path": "",
        "format": "- [ ] {text}  ^{time}",
        "docs": "An Obsidian vault is a folder of Markdown files. Point this at "
                "a note inside it - no account, no token, works offline.",
    },
    "notion": {
        "type": "mcp",
        "label": "Notion",
        "enabled": False,
        "command": "npx",
        "args": ["-y", "@notionhq/notion-mcp-server"],
        "env": {"NOTION_TOKEN": ""},
        "tool": "",
        "args_map": {"content": "{text}"},
        "docs": "https://developers.notion.com/docs/mcp",
    },
    "todoist": {
        "type": "mcp",
        "label": "Todoist",
        "enabled": False,
        "command": "npx",
        "args": ["-y", "@doist/todoist-mcp"],
        "env": {"TODOIST_API_KEY": ""},
        "tool": "",
        "args_map": {"content": "{text}"},
        "docs": "https://developer.todoist.com/",
    },
    "webhook": {
        "type": "webhook",
        "label": "Webhook",
        "enabled": False,
        "url": "",
        "docs": "Any inbound webhook - Zapier, Make, n8n, Discord, your own server.",
    },
}


class Registry:
    def __init__(self, path=CONNECTORS_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._config = self._read()
        self._instances = {}
        self._build()

    def _read(self):
        if self._path.exists():
            try:
                stored = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                stored = {}
        else:
            stored = {}

        # Merge so new presets appear for existing users without clobbering
        # anything they have already filled in.
        merged = {}
        for key, defaults in DEFAULT_CONFIG.items():
            merged[key] = {**defaults, **stored.get(key, {})}
        for key, value in stored.items():
            if key not in merged:
                merged[key] = value
        return merged

    def _write(self):
        self._path.write_text(
            json.dumps(self._config, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _build(self):
        self._instances = {}
        for name, config in self._config.items():
            factory = TYPES.get(config.get("type"))
            if factory is None:
                continue
            self._instances[name] = factory(name, config)

    # ------------------------------------------------------------------ api

    def all(self):
        return list(self._instances.values())

    def get(self, name):
        return self._instances.get(name)

    def describe_all(self):
        out = []
        for name, connector in self._instances.items():
            info = connector.describe()
            config = self._config[name]
            info["label"] = config.get("label", name)
            info["docs"] = config.get("docs", "")
            out.append(info)
        return out

    def update(self, name, changes):
        with self._lock:
            if name not in self._config:
                return None
            # Merge nested env rather than replacing it wholesale, so setting
            # one variable does not wipe the others.
            if "env" in changes and isinstance(changes["env"], dict):
                merged_env = {**(self._config[name].get("env") or {}), **changes["env"]}
                changes = {**changes, "env": merged_env}
            self._config[name].update(changes)
            self._write()
            self._build()
        return self._instances.get(name)

    def active(self):
        return [c for c in self._instances.values() if c.enabled and c.is_configured]

    def deliver_note(self, text):
        """Mirror a note to every live connector. Never raises."""
        results = []
        for connector in self.active():
            try:
                delivery = connector.send_note(text)
            except Exception as exc:
                connector.last_error = str(exc)
                results.append((connector.name, False, str(exc)))
                continue
            results.append((connector.name, delivery.ok, delivery.detail))
        return results


registry = Registry()
