/* Sayso browser extension — the half of the product that lives in the browser.

   The daemon on this machine owns the microphone, the hotkey and the speech
   model. It cannot close a tab or scroll a page; nothing outside the browser
   can. So it publishes those commands on its event stream and this worker
   carries them out.

   The toolbar icon doubles as the tally lamp: it goes red while the key is
   held. That is why there is no content script — the always-visible indicator
   costs no page access at all. */

const DAEMON = "http://127.0.0.1:5000";
const PING_SECONDS = 10;

let stream = null;

/* Badge states mirror the console's lamp colours exactly. */
const BADGE = {
  listening:    { text: "●", color: "#e04a25" },
  transcribing: { text: "•", color: "#f0a830" },
  executing:    { text: "•", color: "#f0a830" },
  loading:      { text: "·", color: "#6d5f4d" },
  error:        { text: "!", color: "#e04a25" },
  idle:         { text: "",  color: "#86a86b" },
  offline:      { text: "×", color: "#6d5f4d" },
};

function setBadge(state) {
  const badge = BADGE[state] || BADGE.idle;
  chrome.action.setBadgeText({ text: badge.text });
  chrome.action.setBadgeBackgroundColor({ color: badge.color });
}

/* ---------------------------------------------------------------- actions */

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function cycleTab(step) {
  const tabs = await chrome.tabs.query({ currentWindow: true });
  if (tabs.length < 2) return;
  const current = tabs.findIndex((t) => t.active);
  const next = (current + step + tabs.length) % tabs.length;
  await chrome.tabs.update(tabs[next].id, { active: true });
}

async function scrollActive(mode) {
  const tab = await activeTab();
  // chrome:// and the web store reject injection; nothing to do but skip.
  if (!tab || !/^https?:/.test(tab.url || "")) return;
  await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    args: [mode],
    func: (how) => {
      const step = Math.round(window.innerHeight * 0.85);
      if (how === "top") window.scrollTo({ top: 0, behavior: "smooth" });
      else if (how === "bottom")
        window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
      else window.scrollBy({ top: how === "up" ? -step : step, behavior: "smooth" });
    },
  });
}

const ACTIONS = {
  close_tab: async () => {
    const tab = await activeTab();
    if (tab) await chrome.tabs.remove(tab.id);
  },
  new_tab: async () => {
    await chrome.tabs.create({});
  },
  reopen_tab: async () => {
    await chrome.sessions.restore();
  },
  next_tab: () => cycleTab(1),
  previous_tab: () => cycleTab(-1),
  reload: async () => {
    const tab = await activeTab();
    if (tab) await chrome.tabs.reload(tab.id);
  },
  scroll_up: () => scrollActive("up"),
  scroll_down: () => scrollActive("down"),
  scroll_top: () => scrollActive("top"),
  scroll_bottom: () => scrollActive("bottom"),
};

async function run(action) {
  const handler = ACTIONS[action];
  if (!handler) return;
  try {
    await handler();
  } catch (error) {
    console.warn("[sayso] action failed", action, error);
  }
}

/* ------------------------------------------------------------- connection */

async function ping() {
  try {
    await fetch(`${DAEMON}/api/extension/ping`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ browser: navigator.userAgent.includes("Edg") ? "Edge" : "Chrome" }),
    });
    return true;
  } catch {
    setBadge("offline");
    return false;
  }
}

function connect() {
  if (stream && stream.readyState !== EventSource.CLOSED) return;

  stream = new EventSource(`${DAEMON}/api/events`);

  stream.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.kind === "status") setBadge(event.status);
    else if (event.kind === "browser_action") run(event.action);
  };

  stream.onerror = () => {
    setBadge("offline");
    // EventSource retries on its own; the alarm below is the backstop for a
    // service worker that got shut down mid-retry.
    stream.close();
    stream = null;
  };
}

async function tick() {
  const alive = await ping();
  if (alive) connect();
}

/* The daemon's SSE keepalive arrives every 15 s, which keeps this worker from
   going idle. The alarm is the backstop for when Chrome shuts it down anyway. */
chrome.alarms.create("sayso-keepalive", { periodInMinutes: 1 });
chrome.alarms.onAlarm.addListener(tick);
chrome.runtime.onStartup.addListener(tick);
chrome.runtime.onInstalled.addListener(tick);

setInterval(tick, PING_SECONDS * 1000);
tick();
