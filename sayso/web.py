"""Flask dashboard: live view of what Sayso is hearing and doing.

Also a full text fallback - every voice command can be typed instead, which
makes the app demoable on a machine with no working microphone.

Connector secrets are write-only here: tokens can be set through the API but
are never sent back to the browser, only the names of the variables they fill.
"""

import json
import queue

from flask import Flask, Response, jsonify, render_template, request

from . import __version__
from .aliases import store as alias_store
from .config import ROOT, settings
from .connectors import registry
from .daemon import daemon
from .events import bus
from .history import history
from .notes import store
from .timers import scheduler

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
        "timers": scheduler.active(),
        "missed_timers": scheduler.missed(),
        "aliases": alias_store.all(),
        "connectors": registry.describe_all(),
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


# ------------------------------------------------------------------- notes


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


# ------------------------------------------------------------------ timers


@app.route("/api/timers/<int:timer_id>", methods=["DELETE"])
def api_cancel_timer(timer_id):
    timer = scheduler.cancel(timer_id)
    if timer is None:
        return jsonify({"error": "not found"}), 404
    bus.publish("timers_changed")
    return jsonify({"cancelled": timer})


@app.route("/api/timers/clear", methods=["POST"])
def api_clear_timers():
    count = scheduler.cancel_all()
    scheduler.clear_missed()
    bus.publish("timers_changed")
    return jsonify({"cancelled": count})


# ----------------------------------------------------------------- aliases


@app.route("/api/aliases", methods=["POST"])
def api_add_alias():
    body = request.json or {}
    phrase = (body.get("phrase") or "").strip()
    target = (body.get("target") or "").strip()
    if not phrase or not target:
        return jsonify({"error": "phrase and target are required"}), 400
    saved = alias_store.add(phrase, target)
    bus.publish("aliases_changed")
    return jsonify({"saved": saved})


@app.route("/api/aliases/<path:phrase>", methods=["DELETE"])
def api_delete_alias(phrase):
    removed = alias_store.remove(phrase)
    if removed is None:
        return jsonify({"error": "not found"}), 404
    bus.publish("aliases_changed")
    return jsonify({"removed": removed})


# -------------------------------------------------------------- connectors


@app.route("/api/connectors")
def api_connectors():
    return jsonify({"connectors": registry.describe_all()})


@app.route("/api/connectors/<name>", methods=["POST"])
def api_update_connector(name):
    changes = request.json or {}
    connector = registry.update(name, changes)
    if connector is None:
        return jsonify({"error": "unknown connector"}), 404
    bus.publish("connectors_changed")
    return jsonify({"connector": connector.describe()})


@app.route("/api/connectors/<name>/tools")
def api_connector_tools(name):
    """Ask an MCP server what it can do, so its tool can be picked from a list."""
    connector = registry.get(name)
    if connector is None:
        return jsonify({"error": "unknown connector"}), 404
    if not hasattr(connector, "list_tools"):
        return jsonify({"tools": []})
    tools = connector.list_tools()
    return jsonify({"tools": tools, "error": connector.last_error})


@app.route("/api/connectors/<name>/test", methods=["POST"])
def api_test_connector(name):
    connector = registry.get(name)
    if connector is None:
        return jsonify({"error": "unknown connector"}), 404
    text = (request.json or {}).get("text") or "Test note from Sayso"
    delivery = connector.send_note(text)
    bus.publish("connectors_changed")
    return jsonify({"ok": delivery.ok, "detail": delivery.detail})


# ----------------------------------------------------------------- history


@app.route("/api/history/clear", methods=["POST"])
def api_clear_history():
    history.clear()
    return jsonify({"cleared": True})
