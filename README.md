# Sayso

**Hold a key. Say what you want. It happens.**

An offline voice controller for your laptop, with a live web dashboard.
Built for Iris Hacks 2026.

The name is from the English *"by my say-so"* — you said so, so it happened.

---

## The problem

Every small thing on a computer costs the same four steps: reach for the mouse,
find the window, click into the address bar, type. Opening YouTube is a
ten-second errand. Writing down an idea before it evaporates means leaving
whatever you were doing and finding somewhere to put it.

The interface is the tax. The intent — *"open YouTube"*, *"remember to submit
before midnight"* — takes half a second to say.

Sayso removes the steps between the thought and the result. Hold `Ctrl+Alt+S`,
say it, let go. Nothing is typed, no window is switched, no tab is hunted for.

## Why it is not just a wrapper around a model

Speech recognition is one component inside the system, not the product. Take the
model out and there is still a global hotkey daemon, a push-to-talk audio
pipeline, an intent grammar, an action executor, a persistent note store and a
live-streaming dashboard. The model turns air into a string; everything
interesting happens after that.

And it **does** things — opens pages, writes files, checks items off — rather
than printing text about them.

---

## How it works

```
      Ctrl+Alt+S held down
              │
              ▼
   pynput global hotkey listener          (any app, any window)
              │
              ▼
   sounddevice ─ 16 kHz mono float32 ─ straight into memory
              │  (key released)
              ▼
   faster-whisper  tiny.en  int8          100% local, no network
              │
              ▼
   intent parser ─ regex grammar          "open youtube through google"
              │                             → open_via_google(target=youtube)
              ▼
   action executor
       ├── browser: webbrowser.open()
       ├── notes:   JSON store on disk
       └── voice:   pyttsx3 → Windows SAPI5
              │
              ▼
   event bus ──SSE──▶  Flask dashboard at localhost:5000
```

Three threads keep it responsive. The pynput listener only starts and stops the
recorder, so it never blocks and never drops a keystroke. A single worker thread
does transcription and execution, which also serialises Whisper — CTranslate2 is
not safe to call concurrently. Flask serves the dashboard on its own threads.

---

## Web app today, desktop app whenever it wants to be

Sayso is already both, and that is the point of the layering.

The part that matters — the hotkey listener, the microphone, the speech model,
the parser, the executor — is a **native desktop background process**. It has no
browser in it and does not need one. It works while you are in a game, a PDF or
another app entirely; that is the whole reason it is not a web page with a
microphone button.

The **web dashboard is a view onto that process**, not the process itself. The
daemon publishes to an in-memory event bus (`sayso/events.py`); Flask
(`sayso/web.py`) subscribes to that bus and streams it to the browser. The
daemon has no idea Flask exists.

So turning it into a "normal" desktop app means replacing one file. Point a Tk,
Qt or Electron window at the same event bus and the same REST calls, and nothing
in the voice pipeline changes. The dashboard is deliberately not load-bearing:
kill it and every voice command still works.

The web version is what ships now because it is the fastest thing to demo, runs
on any machine with a browser, and satisfies the hackathon's web-app brief.

---

## Running it

```bash
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python run.py
```

The dashboard opens at `http://127.0.0.1:5000`. The first run downloads the
speech model once (~75 MB); after that you can turn the Wi-Fi off entirely and
everything still works.

Run the tests with:

```bash
.venv\Scripts\python tests\test_intents.py
```

---

## What it understands

Hold `Ctrl+Alt+S`, speak, release. Every command can also be typed into the
dashboard, which makes it demoable on a machine with no working microphone.

**Opening and searching**

| Say | It does |
|---|---|
| `open youtube` | opens YouTube |
| `open youtube through google` | opens Google, then YouTube — the manual route, automated |
| `google how to pitch a hackathon project` | Google results |
| `search lofi beats on youtube` | YouTube results |
| `go to github.com` | opens that domain |

Unknown single words are treated as `<word>.com`; longer phrases fall back to a
search, so it degrades sensibly instead of failing.

**Notes**

| Say | It does |
|---|---|
| `note: finish the slides, email the mentor` | saves **two** separate notes |
| `remind me to submit before midnight` | saves one note |
| `read my notes` | reads the list out loud |
| `what do I have today` | same |
| `check off 1` | ticks the first item |
| `delete the last note` | removes it |
| `clear all my notes` | empties the list |

Dictation arrives as one blob, so a note is split on commas, semicolons, `and
then` and `also` — one spoken sentence becomes the right number of list items.

---

## Technologies

| Layer | Choice | Why |
|---|---|---|
| Speech-to-text | `faster-whisper` (CTranslate2), `tiny.en`, int8 | offline, ~75 MB, no API key |
| Hotkey | `pynput` | global key hook that works outside the focused window |
| Audio | `sounddevice` / PortAudio | records at Whisper's native 16 kHz, no resampling |
| Intent parsing | Python `re` grammar | instant, offline, cannot invent an action |
| Speech output | `pyttsx3` → SAPI5 | offline voice, already on Windows |
| Web | Flask + Server-Sent Events | live dashboard without a websocket dependency |
| Frontend | vanilla HTML/CSS/JS | no build step |
| Storage | JSON on disk | notes and history survive restarts |

Nothing leaves the machine. There is no account, no API key and no request to
any server.

---

## Decisions made from measurements, not guesses

**Model size.** Timed on the 4-core / 6 GB laptop this was built on, averaged
over spoken test commands:

| Model | Per command | Commands parsed correctly |
|---|---|---|
| `tiny.en` | ~1.7–2.2 s | 4/4 |
| `base.en` | ~3.4 s | 4/4 |
| `small.en` | ~25–30 s | 4/4 |

`small.en` is unusable on this hardware — worth knowing before it wrecks a live
demo. `tiny.en` is twice as fast as `base.en` with no accuracy cost on short
commands, so it is the default. `base.en` is one line away in `sayso/config.py`
if you dictate long notes and want the accuracy more than the speed.

Decoder settings (VAD on/off, timestamps on/off) were also measured, and the
differences turned out to be smaller than the run-to-run noise on a busy 4-core
machine — the same configuration timed 2.17 s and 4.48 s on two runs. So they
were left at the safe defaults rather than tuned against noise.

**Testing speech without speaking.** The end-to-end pipeline is verified by
synthesizing commands with the TTS engine, writing them to WAV, and feeding them
back through Whisper and the parser — a real audio round trip that runs
unattended.

---

## Challenges

**A bare `S` key cannot be a hotkey.** The original design was one key, `S` for
Speak. It would swallow the letter "s" in every text field on the machine.
Push-to-talk on `Ctrl+Alt+S` keeps the one-gesture feel — hold, talk, release —
without breaking typing, and it cannot be left listening by accident.

**Windows reports `Ctrl+S` as `\x13`, not `"s"`.** Matching on the character
silently failed. The listener matches on virtual key codes instead, with the
control character as a fallback.

**Releasing a modifier had to end the recording too.** Letting go of `Ctrl`
while still holding `S` used to leave the microphone open with no way to stop
it. Releasing any required modifier now ends the utterance.

**`faster-whisper` 1.0.3 broke against current `huggingface-hub`.** The model
failed to load with `No module named 'requests'`: hub 1.x dropped `requests`,
which faster-whisper still imports directly. Both are pinned in
`requirements.txt`.

**Whisper invents text when handed silence.** A known failure mode — an
accidental keypress could fire a real command. Guarded three ways: recordings
under 0.35 s are discarded, VAD filtering is on, and an empty transcript stops
the pipeline before the parser. Tested against synthetic silence, which now
produces nothing.

**pyttsx3 deadlocks if driven from two threads.** All speech goes through one
dedicated worker thread, with a fresh engine per utterance, which is what SAPI5
tolerates.

---

## Project structure

```
sayso/
  config.py     settings, persisted to data/settings.json
  audio.py      push-to-talk microphone capture
  stt.py        faster-whisper wrapper
  intents.py    the command grammar
  actions.py    executes intents: browser, notes, speech
  notes.py      note storage and dictation splitting
  hotkey.py     global push-to-talk listener
  daemon.py     orchestration and threading
  tts.py        offline speech output
  events.py     pub/sub bus feeding the dashboard
  web.py        Flask routes and the SSE stream
  history.py    rolling command log
templates/      dashboard markup
static/         dashboard styles and client
tests/          intent parser tests
run.py          starts the daemon and the dashboard
```
