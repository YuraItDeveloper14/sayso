/* Popup: a small window onto the daemon, using the same REST and SSE the
   dashboard uses. It lives only while it is open, so it just subscribes and
   tears down with the page. */

const DAEMON = "http://127.0.0.1:5000";
const SEGMENTS = 20;
const HOT_FROM = 16;
const PEAK_FROM = 19;

const el = (id) => document.getElementById(id);
const lamp = el("lamp");
const state = el("state");
const said = el("said");
const did = el("did");

const segments = [];
for (let i = 0; i < SEGMENTS; i += 1) {
  const seg = document.createElement("span");
  seg.className = "segment";
  el("meter").append(seg);
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

function setStatus(status, detail) {
  lamp.dataset.state = status;
  state.textContent = detail || status;
  if (status !== "listening") setLevel(0);
}

function showEntry(entry) {
  said.textContent = `“${entry.transcript}”`;
  said.classList.remove("waiting");
  did.textContent = entry.display;
  did.classList.toggle("bad", !entry.ok);
}

async function load() {
  try {
    const res = await fetch(`${DAEMON}/api/state`);
    const data = await res.json();
    setStatus(data.status, data.detail);
    el("foot").textContent = data.extension.connected
      ? `Connected · model ${data.settings.model} · hold ${data.settings.hotkey}`
      : "Daemon reachable, extension not registered yet.";
    if (data.history.length) showEntry(data.history[0]);
  } catch {
    setStatus("offline", "daemon not running");
    el("foot").textContent = "Start it with: python run.py";
  }
}

function connect() {
  const stream = new EventSource(`${DAEMON}/api/events`);
  stream.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.kind === "status") setStatus(event.status, event.detail);
    else if (event.kind === "level") setLevel(event.level);
    else if (event.kind === "command") showEntry(event.entry);
    else if (event.kind === "transcript") {
      said.textContent = event.text ? `“${event.text}”` : "…";
      said.classList.remove("waiting");
      did.textContent = "";
    }
  };
  stream.onerror = () => setStatus("offline", "reconnecting");
  window.addEventListener("unload", () => stream.close());
}

function run(text) {
  return fetch(`${DAEMON}/api/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

el("composer").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = el("command");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  run(text);
});

document.querySelectorAll(".tips li").forEach((tip) => {
  tip.addEventListener("click", () => run(tip.textContent));
});

said.classList.add("waiting");
setLevel(0);
load();
connect();
