#!/usr/bin/env python3
"""vmangos-ondemand control panel."""

import json
import os
import queue
import subprocess

from flask import Flask, Response, jsonify, render_template, request

from accounts import create_account, delete_account, list_accounts, set_gmlevel, set_password
from actions import COMMANDS, build_extract_command, get_service_status, get_setup_status
from tasks import TaskStore

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tasks = TaskStore()


def get_realm_host():
    """Host for realmlist: how the user reached this panel (same as what WoW client needs)."""
    if not request.host:
        return None
    return request.host.rsplit(":", 1)[0] or None


@app.route("/")
def index():
    return render_template("index.html", realm_host=get_realm_host())


@app.route("/api/status")
def api_status():
    services = get_service_status(BASE_DIR)
    if services is None:
        return jsonify({"error": "Docker not available"}), 503
    return jsonify(services)


@app.route("/api/setup-status")
def api_setup_status():
    return jsonify(get_setup_status(BASE_DIR))


@app.route("/api/action", methods=["POST"])
def api_action():
    data = request.json or {}
    action = data.get("action")

    if action and action.startswith("extract"):
        client_path = data.get("client_path", "").strip()
        if not client_path:
            return jsonify({"error": "WoW client path is required"}), 400
        client_build = data.get("client_build", "5875").strip() or "5875"
        label, cmd = build_extract_command(action, client_path, client_build)
        task = tasks.create(label, cmd, BASE_DIR)
        return jsonify({"task_id": task.id, "name": task.name})

    if action not in COMMANDS:
        return jsonify({"error": f"Unknown action: {action}"}), 400

    name, cmd = COMMANDS[action]
    if action in ("compile", "compile-extractors"):
        client_build = data.get("client_build", "5875").strip() or "5875"
        cmd = cmd.replace(" build", f" -e CLIENT_BUILD={client_build} build")
    task = tasks.create(name, cmd, BASE_DIR)
    return jsonify({"task_id": task.id, "name": task.name})


@app.route("/api/tasks")
def api_tasks():
    return jsonify([
        {
            "id": t.id,
            "name": t.name,
            "status": t.status,
            "exit_code": t.exit_code,
            "started_at": t.started_at,
        }
        for t in tasks.recent()
    ])


@app.route("/api/tasks/<task_id>/stream")
def api_task_stream(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    def generate():
        q = task.subscribe()
        while True:
            try:
                line = q.get(timeout=30)
                if line is None:
                    yield (
                        f"event: done\n"
                        f"data: {json.dumps({'exit_code': task.exit_code, 'status': task.status})}\n\n"
                    )
                    break
                yield f"data: {json.dumps({'line': line})}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"

    return Response(
        generate(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/logs/<service>")
def api_logs(service):
    if service not in ("mangosd", "realmd", "db"):
        return jsonify({"error": "Unknown service"}), 404

    def generate():
        process = subprocess.Popen(
            ["docker", "compose", "logs", "-f", "--tail", "200", service],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=BASE_DIR,
            text=True,
            bufsize=1,
        )
        try:
            for line in iter(process.stdout.readline, ""):
                yield f"data: {json.dumps({'line': line})}\n\n"
        except GeneratorExit:
            process.kill()
            process.wait()

    return Response(
        generate(),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/accounts")
def api_accounts():
    accounts, err = list_accounts(BASE_DIR)
    if accounts is None:
        return jsonify({"error": err or "Database unavailable"}), 503
    return jsonify(accounts)


@app.route("/api/accounts", methods=["POST"])
def api_create_account():
    data = request.json or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    ok, err = create_account(BASE_DIR, username, password)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/accounts/<username>/password", methods=["PUT"])
def api_set_password(username):
    data = request.json or {}
    password = data.get("password", "").strip()
    if not password:
        return jsonify({"error": "Password is required"}), 400
    ok, err = set_password(BASE_DIR, username, password)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/accounts/<username>/gmlevel", methods=["PUT"])
def api_set_gmlevel(username):
    data = request.json or {}
    gmlevel = data.get("gmlevel")
    ok, err = set_gmlevel(BASE_DIR, username, gmlevel)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/accounts/<username>", methods=["DELETE"])
def api_delete_account(username):
    ok, err = delete_account(BASE_DIR, username)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("vmangos-ondemand")
    print(f"Project: {BASE_DIR}")
    print("Open http://localhost:5555")
    app.run(host="0.0.0.0", port=5555, debug=False, threaded=True)
