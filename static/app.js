/* Console client: fetches state over REST, then follows the daemon live over
   Server-Sent Events. Everything on screen is a view of the daemon; nothing is
   decided here. */

const el = (id) => document.getElementById(id);

const tally = el("tally");
const tallyState = el("tally-state");
const meter = el("meter");
const transcriptEl = el("transcript");
const resultEl = el("result");
const feedEl = el("feed");
const notesEl = el("notes");
const timersEl = el("timers");
const aliasesEl = el("aliases");
const connectorsEl = el("connectors");
const noteCount = el("note-count");

const SEGMENTS = 20;
// Measured against real speech: a normal speaking voice lands around 14-16
// segments, so the amber and red zones sit above that. The meter should only
// change colour when you are actually loud.
const HOT_FROM = 16;
const PEAK_FROM = 19;

const STATE_WORDS = {
  loading: "warming up",
  idle: "standby",
  listening: "live",
  transcribing: "decoding",
  executing: "acting",
  error: "fault",
};

/* What the log says happened. The parser's own intent names are useful for
   debugging and meaningless to anyone reading the screen. */
const INTENT_LABELS = {
  open_site: "opened",
  open_via_google: "via Google",
  search: "searched",
  site_search: "searched",
  write_note: "noted",
  read_notes: "read out",
  complete_note: "checked off",
  delete_note: "deleted",
  clear_notes: "cleared",
  set_timer: "timer set",
  cancel_timers: "timers off",
  list_timers: "timers",
  dismiss_alarm: "alarm off",
  teach_alias: "learned",
  forget_alias: "forgot",
  list_aliases: "shortcuts",
  undo: "undone",
  browser: "browser",
  unknown: "not understood",
  noise: "not speech",
};

/* Which panel each stream event invalidates. */
const REFRESHERS = {
  notes_changed: renderNotesFromState,
  timers_changed: renderTimersFromState,
  aliases_changed: renderAliasesFromState,
  connectors_changed: renderConnectorsFromState,
  extension_changed: renderExtensionFromState,
  alarm_changed: renderAlarmFromState,
  state_changed: renderAll,
};

let openJack = null; // which connector row is expanded

/* ---------------------------------------------------------------- meter */

const segments = [];
for (let i = 0; i < SEGMENTS; i += 1) {
  const seg = document.createElement("span");
  seg.className = "segment";
  meter.append(seg);
  segments.push(seg);
}

function setLevel(level) {
  const lit = Math.round(level * SEGMENTS);
  segments.forEach((seg, i) => {
    const on = i < lit;
    seg.classList.toggle("lit", on);
    seg.classList.toggle("hot", on && i >= HOT_FROM && i < PEAK_FROM);
    seg.classList.toggle("peak", on && i >= PEAK_FROM);
  });
}

/* --------------------------------------------------------------- status */

let listening = false;

function setStatus(status, detail) {
  tally.dataset.state = status;
  tallyState.textContent = STATE_WORDS[status] || status;
  el("rail-engine").textContent = detail || STATE_WORDS[status] || status;
  listening = status === "listening";
  el("tally-cancel").hidden = !listening;
  tally.setAttribute(
    "aria-label",
    listening ? "Click to send what you said" : "Click to start listening"
  );
  if (!listening) setLevel(0);
}

/* Click to talk, click again to send, Escape to throw it away — the same three
   moves as the hotkey, for when your hands are already on the screen. */
function listen(action) {
  return fetch(`/api/listen/${action}`, { method: "POST" });
}

tally.addEventListener("click", () => listen(listening ? "stop" : "start"));
el("tally-cancel").addEventListener("click", () => listen("cancel"));

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && listening) {
    event.preventDefault();
    listen("cancel");
  }
});

function timeLabel(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function countdown(seconds) {
  const total = Math.max(0, Math.round(seconds));
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h}:${String(m % 60).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${m}:${String(s).padStart(2, "0")}`;
}

function fill(parent, children, emptyText) {
  parent.replaceChildren();
  if (!children.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = emptyText;
    parent.append(li);
    return;
  }
  children.forEach((child) => parent.append(child));
}

/* ------------------------------------------------------------------ log */

function logEntry(entry) {
  const li = document.createElement("li");
  li.className = entry.ok ? "entry" : "entry failed";

  const time = document.createElement("span");
  time.className = "entry-time";
  time.textContent = timeLabel(entry.ts);

  const body = document.createElement("div");

  const said = document.createElement("div");
  said.className = "entry-said";
  said.dataset.source = entry.source === "voice" ? "🎙" : "⌨";
  said.append(document.createTextNode(entry.transcript));

  const did = document.createElement("div");
  did.className = "entry-did";
  did.textContent = entry.display;

  body.append(said, did);

  const intent = document.createElement("span");
  intent.className = "entry-intent";
  intent.textContent = INTENT_LABELS[entry.intent] || entry.intent;

  li.append(time, body, intent);
  return li;
}

function renderLog(entries) {
  fill(feedEl, entries.map(logEntry), "Nothing yet. Speak, or type a command below.");
}

/* ---------------------------------------------------------------- notes */

function renderNotes(notes) {
  const pending = notes.filter((n) => !n.done);
  noteCount.textContent = pending.length;

  // Numbering follows the pending list so "check off 2" on screen means the
  // same thing it means out loud.
  let position = 0;
  const rows = notes.map((note) => {
    const li = document.createElement("li");
    li.className = note.done ? "note done" : "note";

    const index = document.createElement("span");
    index.className = "note-index";
    index.textContent = note.done ? "·" : `${++position}.`;

    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "note-check";
    check.checked = note.done;
    check.setAttribute("aria-label", `Done: ${note.text}`);
    check.addEventListener("change", () =>
      fetch(`/api/notes/${note.id}/toggle`, { method: "POST" })
    );

    const text = document.createElement("span");
    text.className = "note-text";
    text.textContent = note.text;

    const remove = document.createElement("button");
    remove.className = "row-remove";
    remove.title = "Delete note";
    remove.textContent = "×";
    remove.addEventListener("click", () =>
      fetch(`/api/notes/${note.id}`, { method: "DELETE" })
    );

    li.append(index, check, text, remove);
    return li;
  });

  fill(notesEl, rows, "Say “note: finish the slides”.");
}

/* --------------------------------------------------------------- timers */

function renderTimers(timers) {
  const rows = timers.map((timer) => {
    const li = document.createElement("li");
    li.className = "timer";
    li.dataset.at = timer.at;

    const remaining = document.createElement("span");
    remaining.className = "timer-remaining";
    remaining.textContent = countdown(timer.remaining);

    const label = document.createElement("span");
    label.className = "timer-label";
    label.textContent = timer.label;

    const cancel = document.createElement("button");
    cancel.className = "row-remove";
    cancel.title = "Cancel timer";
    cancel.textContent = "×";
    cancel.addEventListener("click", () =>
      fetch(`/api/timers/${timer.id}`, { method: "DELETE" })
    );

    li.append(remaining, label, cancel);
    return li;
  });

  fill(timersEl, rows, "Say “remind me in 20 minutes to stretch”.");
}

/* ---------------------------------------------------------------- alarm */

let alarmWatch = null;

function renderAlarm(alarm) {
  const button = el("alarm-stop");
  button.hidden = !alarm.ringing;
  el("alarm-label").textContent = alarm.label ? `“${alarm.label}”` : "";

  // Shown optimistically the moment a timer fires, so a missed "stopped" event
  // used to leave it on screen for good. While it is up, keep asking the daemon
  // whether anything is actually still ringing.
  if (alarm.ringing && alarmWatch === null) {
    alarmWatch = setInterval(async () => {
      const state = await loadState().catch(() => null);
      if (!state || !state.alarm.ringing) {
        clearInterval(alarmWatch);
        alarmWatch = null;
        button.hidden = true;
      }
    }, 4000);
  } else if (!alarm.ringing && alarmWatch !== null) {
    clearInterval(alarmWatch);
    alarmWatch = null;
  }
}

function renderExtension(extension) {
  el("rail-extension").textContent = extension.connected
    ? `${extension.browser || "connected"}`
    : "no extension";
}

function renderEngines(state) {
  el("rail-voice").textContent = state.settings.voice || "…";
  el("rail-llm").textContent = state.llm.available
    ? state.llm.model.split("/").pop()
    : state.llm.has_key
      ? "off"
      : "no key";
}

// One ticker for every countdown, rather than one per row.
setInterval(() => {
  const now = Date.now() / 1000;
  timersEl.querySelectorAll(".timer[data-at]").forEach((row) => {
    const remaining = Number(row.dataset.at) - now;
    row.querySelector(".timer-remaining").textContent = countdown(remaining);
  });
}, 1000);

/* ------------------------------------------------------------ shortcuts */

function renderAliases(aliases) {
  const rows = aliases.map((alias) => {
    const li = document.createElement("li");
    li.className = "alias";

    const phrase = document.createElement("span");
    phrase.className = "alias-phrase";
    phrase.textContent = alias.phrase;

    const arrow = document.createElement("span");
    arrow.className = "alias-arrow";
    arrow.textContent = "→";

    const target = document.createElement("span");
    target.className = "alias-target";
    target.textContent = alias.target;
    target.title = alias.target;

    const remove = document.createElement("button");
    remove.className = "row-remove";
    remove.title = "Forget shortcut";
    remove.textContent = "×";
    remove.addEventListener("click", () =>
      fetch(`/api/aliases/${encodeURIComponent(alias.phrase)}`, { method: "DELETE" })
    );

    li.append(phrase, arrow, target, remove);
    return li;
  });

  fill(aliasesEl, rows, "Say “when I say my class, open …”.");
}

/* ------------------------------------------------------------ patch bay */

function connectorRow(connector) {
  const li = document.createElement("li");
  li.className = "jack";

  const head = document.createElement("button");
  head.className = "jack-head";
  head.type = "button";
  head.setAttribute("aria-expanded", String(openJack === connector.name));

  const ring = document.createElement("span");
  ring.className = "jack-ring";
  ring.dataset.state = connector.state;

  const name = document.createElement("span");
  name.className = "jack-name";
  name.textContent = connector.label;

  // Say plainly which connectors give up the offline guarantee.
  const net = document.createElement("span");
  net.className = "jack-net";
  net.dataset.network = String(connector.requires_network);
  net.textContent = connector.requires_network ? "needs internet" : "works offline";

  const state = document.createElement("span");
  state.className = "jack-state";
  state.dataset.state = connector.state;
  state.textContent = connector.state === "off" ? "off" : connector.needs || connector.state;

  head.append(ring, name, net, state);
  head.addEventListener("click", () => {
    openJack = openJack === connector.name ? null : connector.name;
    renderConnectorsFromState();
  });
  li.append(head);

  if (openJack !== connector.name) return li;

  const body = document.createElement("div");
  body.className = "jack-body";

  if (connector.docs) {
    const docs = document.createElement("p");
    docs.className = "jack-docs";
    if (connector.docs.startsWith("http")) {
      const link = document.createElement("a");
      link.href = connector.docs;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = connector.docs;
      docs.append("Setup instructions: ", link);
    } else {
      docs.textContent = connector.docs;
    }
    body.append(docs);
  }

  if (connector.command) {
    const command = document.createElement("p");
    command.className = "jack-docs";
    command.textContent = `Runs: ${connector.command}`;
    body.append(command);
  }

  const inputs = {};
  (connector.fields || []).forEach((field) => {
    const label = document.createElement("label");
    label.className = "field";
    const caption = document.createElement("span");
    caption.textContent = field.label;
    const input = document.createElement("input");
    input.type = field.secret ? "password" : "text";
    input.value = field.value || "";
    input.placeholder = field.placeholder || "";
    inputs[field.key] = input;
    label.append(caption, input);
    body.append(label);
  });

  const actions = document.createElement("div");
  actions.className = "jack-actions";

  const save = document.createElement("button");
  save.className = "primary";
  save.type = "button";
  save.textContent = "Save";
  save.addEventListener("click", async () => {
    const changes = {};
    Object.entries(inputs).forEach(([key, input]) => {
      // A blank secret means "leave the stored one alone", not "erase it".
      if (key.startsWith("env.")) {
        if (!input.value) return;
        changes.env = { ...(changes.env || {}), [key.slice(4)]: input.value };
      } else {
        changes[key] = input.value;
      }
    });
    await fetch(`/api/connectors/${connector.name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(changes),
    });
  });

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.textContent = connector.enabled ? "Turn off" : "Turn on";
  toggle.addEventListener("click", () =>
    fetch(`/api/connectors/${connector.name}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !connector.enabled }),
    })
  );

  actions.append(save, toggle);

  const tools = document.createElement("p");
  tools.className = "jack-tools";

  if (connector.type === "MCP") {
    const list = document.createElement("button");
    list.type = "button";
    list.textContent = "List tools";
    list.addEventListener("click", async () => {
      tools.textContent = "Starting the server…";
      const res = await fetch(`/api/connectors/${connector.name}/tools`);
      const data = await res.json();
      tools.textContent = data.tools.length
        ? data.tools.map((t) => t.name).join("\n")
        : data.error || "No tools reported.";
    });
    actions.append(list);
  }

  const test = document.createElement("button");
  test.type = "button";
  test.textContent = "Send a test note";
  test.addEventListener("click", async () => {
    tools.textContent = "Sending…";
    const res = await fetch(`/api/connectors/${connector.name}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: "Test note from Sayso" }),
    });
    const data = await res.json();
    tools.textContent = data.ok ? `Delivered: ${data.detail}` : `Failed: ${data.detail}`;
  });
  actions.append(test);

  body.append(actions, tools);
  li.append(body);
  return li;
}

function renderConnectors(connectors) {
  fill(connectorsEl, connectors.map(connectorRow), "No connectors configured.");
  const live = connectors.filter((c) => c.state === "connected").map((c) => c.label);
  el("rail-links").textContent = live.length ? live.join(", ") : "none";
}

/* ------------------------------------------------------------------ data */

let lastState = null;

async function loadState() {
  const res = await fetch("/api/state");
  lastState = await res.json();
  return lastState;
}

async function renderAll() {
  const state = await loadState();
  setStatus(state.status, state.detail);
  renderLog(state.history);
  renderNotes(state.notes);
  renderTimers(state.timers);
  renderAliases(state.aliases);
  renderConnectors(state.connectors);
  renderAlarm(state.alarm);
  renderExtension(state.extension);
  renderEngines(state);
}

async function renderNotesFromState() {
  renderNotes((await loadState()).notes);
}
async function renderTimersFromState() {
  renderTimers((await loadState()).timers);
}
async function renderAliasesFromState() {
  renderAliases((await loadState()).aliases);
}
async function renderConnectorsFromState() {
  renderConnectors((await loadState()).connectors);
}
async function renderAlarmFromState() {
  renderAlarm((await loadState()).alarm);
}
async function renderExtensionFromState() {
  renderExtension((await loadState()).extension);
}

function connect() {
  const source = new EventSource("/api/events");

  source.onmessage = (message) => {
    const event = JSON.parse(message.data);

    if (REFRESHERS[event.kind]) {
      REFRESHERS[event.kind]();
      return;
    }

    switch (event.kind) {
      case "status":
        setStatus(event.status, event.detail);
        break;
      case "level":
        setLevel(event.level);
        break;
      case "transcript":
        if (event.source === "cancelled") {
          transcriptEl.textContent = "Cancelled — nothing was sent";
          transcriptEl.classList.add("waiting");
        } else {
          transcriptEl.textContent = event.text ? `“${event.text}”` : "…";
          transcriptEl.classList.remove("waiting");
        }
        resultEl.textContent = "";
        resultEl.classList.remove("bad");
        break;
      case "command": {
        const empty = feedEl.querySelector(".empty");
        if (empty) empty.remove();
        feedEl.prepend(logEntry(event.entry));
        while (feedEl.children.length > 40) feedEl.lastElementChild.remove();
        resultEl.textContent = event.entry.display;
        resultEl.classList.toggle("bad", !event.entry.ok);
        break;
      }
      case "timer_fired":
        transcriptEl.textContent = `Reminder: ${event.timer.label}`;
        transcriptEl.classList.remove("waiting");
        resultEl.textContent = "";
        renderAlarm({ ringing: true, label: event.timer.label });
        break;
      case "connector":
        resultEl.textContent = event.ok
          ? `Copied to ${event.connector}`
          : `${event.connector} failed: ${event.detail}`;
        resultEl.classList.toggle("bad", !event.ok);
        break;
      case "log":
        if (event.level === "error") console.error("[sayso]", event.message);
        else console.info("[sayso]", event.message);
        break;
    }
  };

  // EventSource retries on its own, but a dropped stream can mean the daemon
  // restarted, so resync everything once it comes back.
  source.onerror = () => {
    tallyState.textContent = "reconnecting";
    setTimeout(() => renderAll().catch(() => {}), 2500);
  };
}

/* --------------------------------------------------------------- actions */

function runCommand(text) {
  return fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

el("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = el("command-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  runCommand(text);
});

el("note-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = el("note-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  fetch("/api/notes", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
});

el("alias-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const phrase = el("alias-phrase");
  const target = el("alias-target");
  if (!phrase.value.trim() || !target.value.trim()) return;
  fetch("/api/aliases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ phrase: phrase.value.trim(), target: target.value.trim() }),
  });
  phrase.value = "";
  target.value = "";
});

el("clear-notes").addEventListener("click", () =>
  fetch("/api/notes/clear", { method: "POST" })
);

el("clear-timers").addEventListener("click", () =>
  fetch("/api/timers/clear", { method: "POST" })
);

el("clear-history").addEventListener("click", async () => {
  await fetch("/api/history/clear", { method: "POST" });
  renderLog([]);
});

el("undo").addEventListener("click", async () => {
  const res = await fetch("/api/undo", { method: "POST" });
  const data = await res.json();
  resultEl.textContent = data.undone ? `Undid ${data.undone}` : "Nothing to undo";
  resultEl.classList.toggle("bad", !data.undone);
});

el("alarm-stop").addEventListener("click", () =>
  fetch("/api/alarm/stop", { method: "POST" })
);

// These read as documentation, so they must not fire real commands on a click —
// one of them sets a timer, and an alarm nobody asked for is nobody's friend.
// Clicking loads the phrase into the box; running it stays a deliberate act.
document.querySelectorAll(".phrase").forEach((button) => {
  button.addEventListener("click", () => {
    const input = el("command-input");
    input.value = button.textContent;
    input.focus();
    input.scrollIntoView({ block: "center", behavior: "smooth" });
  });
});

transcriptEl.classList.add("waiting");
setLevel(0);
renderAll().catch(() => setStatus("error", "cannot reach the daemon"));
connect();
