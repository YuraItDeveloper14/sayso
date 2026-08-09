"""Talk to a real app through an MCP server.

MCP (Model Context Protocol) servers are how Notion, Todoist, Linear and a
growing list of apps expose their actions. Each one is a process Sayso launches
and speaks to over stdin/stdout, so adding an app means adding a config entry
rather than writing an API client.

Sayso is not an LLM, so it does not guess which tool to call: the config names
the tool and how to fill its arguments. `{text}` in any argument is replaced
with the note. Call `list_tools()` to see what a server offers before mapping it.

The MCP SDK is async and the rest of Sayso is threads, so each connector owns
one background event loop and keeps a single session open on it. Launching a
server per note would cost seconds of `npx` startup every time.
"""

import asyncio
import os
import threading

from .base import Connector, Delivery

CONNECT_TIMEOUT = 45
CALL_TIMEOUT = 30


class MCPConnector(Connector):
    type_name = "MCP"
    # An MCP server can be a purely local program, but every preset shipped
    # here talks to a hosted account. Override per connector in the config.
    requires_network = True

    def __init__(self, name, config):
        super().__init__(name, config)
        self._loop = None
        self._thread = None
        self._session = None
        self._stop = None
        self._ready = threading.Event()
        self._tools = []
        self._start_lock = threading.Lock()

    # --------------------------------------------------------------- config

    @property
    def command(self):
        return (self.config.get("command") or "").strip()

    @property
    def tool(self):
        return (self.config.get("tool") or "").strip()

    @property
    def env(self):
        return {k: str(v) for k, v in (self.config.get("env") or {}).items()}

    @property
    def is_configured(self):
        if not self.command:
            return False
        # A server whose env vars are declared but left blank is a token the
        # user has not pasted yet.
        return all(value for value in self.env.values())

    @property
    def needs(self):
        if not self.command:
            return "add the server command"
        missing = [k for k, v in self.env.items() if not v]
        if missing:
            return f"add {', '.join(missing)}"
        if not self.tool:
            return "pick a tool (open the connector to list them)"
        return ""

    # ------------------------------------------------------------- lifecycle

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:
            self.last_error = str(exc)
        finally:
            self._session = None
            self._ready.set()  # unblock anyone waiting on a failed start
            self._loop.close()
            self._loop = None

    async def _serve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=self.command,
            args=list(self.config.get("args") or []),
            env={**os.environ, **self.env},
        )

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listing = await session.list_tools()
                self._tools = [
                    {"name": t.name, "description": (t.description or "")[:200]}
                    for t in listing.tools
                ]
                self._session = session
                self.last_error = ""
                self._ready.set()
                self._stop = asyncio.Event()
                await self._stop.wait()

    def connect(self):
        """Start the server if it is not already running. Blocking."""
        with self._start_lock:
            if self._session is not None:
                return True
            if not self.is_configured:
                self.last_error = self.needs
                return False

            self._ready.clear()
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name=f"sayso-mcp-{self.name}"
            )
            self._thread.start()

        if not self._ready.wait(CONNECT_TIMEOUT):
            self.last_error = "server did not start in time"
            return False
        return self._session is not None

    def disconnect(self):
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        self._session = None

    # ------------------------------------------------------------------ use

    def list_tools(self):
        """What this server can do. Connects if needed."""
        if self._session is None and not self.connect():
            return []
        return list(self._tools)

    def _arguments_for(self, text):
        mapped = {}
        for key, value in (self.config.get("args_map") or {}).items():
            mapped[key] = value.replace("{text}", text) if isinstance(value, str) else value
        return mapped

    def send_note(self, text):
        if not self.tool:
            return Delivery(False, "no tool selected")
        if self._session is None and not self.connect():
            return Delivery(False, self.last_error or "could not connect")

        future = asyncio.run_coroutine_threadsafe(
            self._session.call_tool(self.tool, self._arguments_for(text)), self._loop
        )
        try:
            result = future.result(timeout=CALL_TIMEOUT)
        except Exception as exc:
            self.last_error = str(exc)
            # The session is likely dead; drop it so the next note reconnects.
            self._session = None
            return Delivery(False, str(exc))

        if getattr(result, "isError", False):
            self.last_error = "server reported an error"
            return Delivery(False, self.last_error)

        self.last_error = ""
        return Delivery(True, f"{self.tool} ok")

    def describe(self):
        info = super().describe()
        info["tool"] = self.tool
        info["command"] = " ".join([self.command, *(self.config.get("args") or [])]).strip()
        info["tools_known"] = len(self._tools)
        # Token names and whether each is filled. The values themselves are
        # never serialised - they stay in data/connectors.json on this machine.
        info["fields"] = [
            {"key": f"env.{key}", "label": key, "value": "", "secret": True,
             "placeholder": "•••• already set" if value else "paste the token"}
            for key, value in sorted(self.env.items())
        ]
        info["fields"].append(
            {"key": "tool", "label": "Tool to call", "value": self.tool,
             "placeholder": "list the tools to see the options"}
        )
        return info
