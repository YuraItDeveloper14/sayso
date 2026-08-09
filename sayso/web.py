"""Flask dashboard: live view of what Sayso is hearing and doing.

Also a full text fallback - every voice command can be typed instead, which
makes the app demoable on a machine with no working microphone.
"""

import json
import queue

from flask import Flask, Response, jsonify, render_template, request

from . import __version__
from .config import ROOT, settings
from .daemon import daemon
from .events import bus
from .history import history
from .notes import store

app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
)


def _state():
    return {
        "status": bus.status,
        "detail": bus.status_detail,
        "model_ready": daemon.model_ready,
        "notes": store.all(),
        "history": history.recent(),
        "settings": {
            "hotkey": settings.hotkey_label,
            "model": settings.model_size,
            "language": settings.language,
            "speak_replies": settings.speak_replies,
        },
        "version": __version__,
    }


@app.route("/")
def index():
    return render_template(
        "index.html", hotkey=settings.hotkey_label, model=settings.model_size
    )


@app.route("/api/state")
def api_state():
    return jsonify(_state())


@app.route("/api/events")
def api_events():
    def stream():
        q = bus.subscribe()
        try:
            hello = {"kind": "status", "status": bus.status, "detail": bus.status_detail}
            yield f"data: {json.dumps(hello)}\n\n"
            while True:
                try:
                    event = q.get(timeout=15)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    # Comment frame keeps proxies and the browser from timing out.
                    yield ": keepalive\n\n"
        finally:
            bus.unsubscribe(q)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/command", methods=["POST"])
def api_command():
    text = (request.json or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "empty command"}), 400
    daemon.submit_text(text)
    return jsonify({"queued": True})


@app.route("/api/notes", methods=["POST"])
def api_add_note():
    text = (request.json or {}).get("text", "").strip()
    if not text:
        return jsonify({"error": "empty note"}), 400
    created = store.add(text, source="typed")
    bus.publish("notes_changed")
    return jsonify({"created": created})


@app.route("/api/notes/<int:note_id>/toggle", methods=["POST"])
def api_toggle_note(note_id):
    note = store.toggle(note_id)
    if note is None:
        return jsonify({"error": "not found"}), 404
    bus.publish("notes_changed")
    return jsonify({"note": note})


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def api_delete_note(note_id):
    note = store.delete(note_id)
    if note is None:
        return jsonify({"error": "not found"}), 404
    bus.publish("notes_changed")
    return jsonify({"deleted": note})


@app.route("/api/notes/clear", methods=["POST"])
def api_clear_notes():
    count = store.clear()
    bus.publish("notes_changed")
    return jsonify({"cleared": count})


@app.route("/api/history/clear", methods=["POST"])
def api_clear_history():
    history.clear()
    return jsonify({"cleared": True})
