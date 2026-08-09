/* Dashboard client: pulls initial state over REST, then follows the daemon
   live over Server-Sent Events. */

const el = (id) => document.getElementById(id);

const orb = el("orb");
const statusDot = el("status-dot");
const statusText = el("status-text");
const transcriptEl = el("transcript");
const resultEl = el("result");
const feedEl = el("feed");
const notesEl = el("notes");
const noteCount = el("note-count");

const STATUS_LABEL = {
  loading: "loading speech model…",
  idle: "ready",
  listening: "listening",
  transcribing: "transcribing",
  executing: "running command",
  error: "error",
};

/* Notes intents get a green tag; everything else is violet. */
const NOTE_INTENTS = new Set([
  "write_note",
  "read_notes",
  "complete_note",
  "delete_note",
  "clear_notes",
]);

function setStatus(status, detail) {
  orb.dataset.state = status;
  statusDot.dataset.state = status;
  statusText.textContent = detail || STATUS_LABEL[status] || status;
}

function timeLabel(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function setTranscript(text) {
  transcriptEl.textContent = text ? `“${text}”` : "";
  transcriptEl.classList.remove("placeholder");
}

/* ------------------------------------------------------------------ feed */

function feedItem(entry) {
  const li = document.createElement("li");
  li.className = "feed-item";

  const tag = document.createElement("span");
  tag.className = "tag";
  if (!entry.ok) tag.classList.add("failed");
  else if (NOTE_INTENTS.has(entry.intent)) tag.classList.add("notes");
  tag.textContent = entry.intent;

  const body = document.createElement("div");
  body.className = "feed-body";

  const said = document.createElement("div");
  said.className = "feed-said";
  const badge = document.createElement("span");
  badge.className = "mic-badge";
  badge.textContent = entry.source === "voice" ? "🎙" : "⌨";
  said.append(badge, document.createTextNode(entry.transcript));

  const did = document.createElement("div");
  did.className = "feed-did";
  did.textContent = entry.display;

  body.append(said, did);

  const meta = document.createElement("div");
  meta.className = "feed-meta";
  meta.textContent = entry.latency ? `${timeLabel(entry.ts)} · ${entry.latency}s` : timeLabel(entry.ts);

  li.append(tag, body, meta);
  return li;
}

function renderFeed(entries) {
  feedEl.replaceChildren();
  if (!entries.length) {
    const empty = document.createElement("li");
    empty.className = "feed-empty";
    empty.textContent = "Nothing yet. Say a command or type one below.";
    feedEl.append(empty);
    return;
  }
  entries.forEach((entry) => feedEl.append(feedItem(entry)));
}

function prependFeed(entry) {
  const empty = feedEl.querySelector(".feed-empty");
  if (empty) empty.remove();
  feedEl.prepend(feedItem(entry));
  while (feedEl.children.length > 40) feedEl.lastElementChild.remove();
}

/* ----------------------------------------------------------------- notes */

function renderNotes(notes) {
  notesEl.replaceChildren();
  const pending = notes.filter((n) => !n.done);
  noteCount.textContent = pending.length;

  if (!notes.length) {
    const empty = document.createElement("li");
    empty.className = "feed-empty";
    empty.textContent = "No notes yet. Try “note: finish the demo”.";
    notesEl.append(empty);
    return;
  }

  // Numbering follows the pending list, so "check off 2" on the dashboard
  // means the same thing it means out loud.
  let position = 0;
  notes.forEach((note) => {
    const li = document.createElement("li");
    li.className = "note-item" + (note.done ? " done" : "");

    const index = document.createElement("span");
    index.className = "note-index";
    index.textContent = note.done ? "·" : `${++position}.`;

    const check = document.createElement("input");
    check.type = "checkbox";
    check.className = "note-check";
    check.checked = note.done;
    check.addEventListener("change", () =>
      fetch(`/api/notes/${note.id}/toggle`, { method: "POST" })
    );

    const text = document.createElement("span");
    text.className = "note-text";
    text.textContent = note.text;

    const del = document.createElement("button");
    del.className = "note-del";
    del.title = "Delete note";
    del.textContent = "×";
    del.addEventListener("click", () =>
      fetch(`/api/notes/${note.id}`, { method: "DELETE" })
    );

    li.append(index, check, text, del);
    notesEl.append(li);
  });
}

/* ------------------------------------------------------------------ data */

async function refreshState() {
  const res = await fetch("/api/state");
  const state = await res.json();
  setStatus(state.status, state.detail);
  renderFeed(state.history);
  renderNotes(state.notes);
}

async function refreshNotes() {
  const res = await fetch("/api/state");
  const state = await res.json();
  renderNotes(state.notes);
}

function connect() {
  const source = new EventSource("/api/events");

  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    switch (event.kind) {
      case "status":
        setStatus(event.status, event.detail);
        break;
      case "transcript":
        setTranscript(event.text);
        resultEl.textContent = "";
        break;
      case "command":
        prependFeed(event.entry);
        resultEl.textContent = event.entry.display;
        resultEl.classList.toggle("failed", !event.entry.ok);
        break;
      case "notes_changed":
        refreshNotes();
        break;
      case "log":
        if (event.level === "error") console.error("[sayso]", event.message);
        else console.info("[sayso]", event.message);
        break;
    }
  };

  // EventSource retries on its own, but a dropped stream can mean the daemon
  // restarted, so resync the whole state once it comes back.
  source.onerror = () => {
    statusText.textContent = "reconnecting…";
    setTimeout(() => refreshState().catch(() => {}), 2500);
  };
}

/* --------------------------------------------------------------- actions */

el("composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = el("command-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  fetch("/api/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
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

el("clear-notes").addEventListener("click", () =>
  fetch("/api/notes/clear", { method: "POST" })
);

el("clear-history").addEventListener("click", async () => {
  await fetch("/api/history/clear", { method: "POST" });
  renderFeed([]);
});

document.querySelectorAll(".example").forEach((button) => {
  button.addEventListener("click", () => {
    el("command-input").value = button.textContent;
    el("composer").requestSubmit();
  });
});

transcriptEl.classList.add("placeholder");
refreshState().catch(() => setStatus("error", "dashboard could not reach the daemon"));
connect();
