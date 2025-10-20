#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web dashboard for PAMT DCA Drop-Buy bot
- Edit .env, start/stop the bot, stream logs, view purchases.json
- Simple Flask app with server-sent events (SSE) for log streaming
- Starts bot script as a subprocess with environment loaded from .env

Usage:
    pip install -r requirements.txt
    python app.py

Open http://127.0.0.1:5000 in your browser.
"""

import os
import sys
import time
import json
import queue
import subprocess
import threading
from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, Response, send_file, abort
)

# Config
ENV_FILE = ".env"
BOT_SCRIPT = "bot_dca_drop_on_drop.py"  # adjust if your bot filename differs
PURCHASES_DEFAULT = "purchases.json"

# Keys exposed in web form (order matters for display)
ENV_KEYS = [
    "UPBIT_ACCESS_KEY",
    "UPBIT_SECRET_KEY",
    "DRY_RUN",
    "SIM_KRW_BALANCE",
    "INSTALLMENTS",
    "MIN_KRW_ORDER",
    "TOTAL_INVEST_FRACTION",
    "TOTAL_INVEST_KRW",
    "ALLOCATIONS",
    "DROP_PCT",
    "DROP_PCT_PER_COIN",
    "INITIAL_BUY",
    "MONITOR_INTERVAL_MIN",
    "MONITOR_INTERVAL_SEC",
    "TARGET_PROFIT_PCT",
    "TARGET_PROFIT_KRW",
    "SELL_FRACTION",
    "PURCHASES_FILE"
]

# Globals
app = Flask(__name__, template_folder="templates", static_folder="static")
bot_proc = None
bot_lock = threading.Lock()
log_queue = queue.Queue()
stdout_reader_thread = None
stop_reader_event = threading.Event()


# --- env helpers ---
def load_env_file(path=ENV_FILE):
    env = {}
    if not os.path.exists(path):
        return env
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except Exception:
        pass
    return env


def save_env_file(env_dict, path=ENV_FILE):
    # write keys in ENV_KEYS order, then other keys
    lines = []
    existing = load_env_file(path)
    written = set()
    for k in ENV_KEYS:
        v = env_dict.get(k, existing.get(k, ""))
        lines.append(f"{k}={v}")
        written.add(k)
    for k, v in env_dict.items():
        if k not in written:
            lines.append(f"{k}={v}")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return True
    except Exception as e:
        app.logger.exception("Failed to save .env: %s", e)
        return False


# --- process & logging ---
def _reader_thread(proc, stop_event):
    """Read stdout lines from proc and push to log_queue"""
    try:
        if not proc or not proc.stdout:
            return
        for raw in proc.stdout:
            if raw is None:
                break
            line = raw.rstrip("\n")
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log_queue.put(f"[{timestamp}] {line}")
            if stop_event.is_set():
                break
    except Exception as e:
        log_queue.put(f"[error] stdout reader exception: {e}")
    finally:
        log_queue.put("[system] BOT_PROCESS_ENDED")


def start_bot_subprocess():
    global bot_proc, stdout_reader_thread, stop_reader_event
    with bot_lock:
        if bot_proc and bot_proc.poll() is None:
            return False, "Bot is already running"
        if not os.path.exists(BOT_SCRIPT):
            return False, f"Bot script not found: {BOT_SCRIPT}"
        env = os.environ.copy()
        file_env = load_env_file()
        for k, v in file_env.items():
            env[k] = v
        # Ensure purchases file env exists
        env.setdefault("PURCHASES_FILE", file_env.get("PURCHASES_FILE", PURCHASES_DEFAULT))
        try:
            bot_proc = subprocess.Popen(
                [sys.executable, BOT_SCRIPT],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                env=env
            )
        except Exception as e:
            return False, f"Failed to start bot: {e}"

        stop_reader_event.clear()
        stdout_reader_thread = threading.Thread(target=_reader_thread, args=(bot_proc, stop_reader_event), daemon=True)
        stdout_reader_thread.start()
        log_queue.put("[system] Bot started")
        return True, "Bot started"


def stop_bot_subprocess():
    global bot_proc, stop_reader_event
    with bot_lock:
        if not bot_proc:
            return False, "Bot is not running"
        try:
            bot_proc.terminate()
            try:
                bot_proc.wait(timeout=5)
            except Exception:
                try:
                    bot_proc.kill()
                    bot_proc.wait(timeout=2)
                except Exception:
                    pass
            stop_reader_event.set()
            log_queue.put("[system] Bot stopped")
        except Exception as e:
            return False, f"Failed to stop bot: {e}"
        finally:
            bot_proc = None
        return True, "Bot stopped"


# --- Flask routes ---
@app.route("/")
def index():
    env = load_env_file()
    # ensure defaults for displayed keys
    data = {k: env.get(k, "") for k in ENV_KEYS}
    return render_template("index.html", env=data)


@app.route("/api/save_env", methods=["POST"])
def api_save_env():
    payload = request.json or {}
    if not payload:
        return jsonify({"ok": False, "error": "no payload"}), 400
    ok = save_env_file(payload)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "save_failed"}), 500


@app.route("/api/load_env", methods=["GET"])
def api_load_env():
    env = load_env_file()
    return jsonify(env)


@app.route("/api/start", methods=["POST"])
def api_start():
    ok, msg = start_bot_subprocess()
    status = {"ok": ok, "message": msg}
    return jsonify(status)


@app.route("/api/stop", methods=["POST"])
def api_stop():
    ok, msg = stop_bot_subprocess()
    status = {"ok": ok, "message": msg}
    return jsonify(status)


@app.route("/api/status", methods=["GET"])
def api_status():
    running = False
    rc = None
    with bot_lock:
        if bot_proc:
            rc = bot_proc.poll()
            running = rc is None
    return jsonify({
        "running": running,
        "returncode": rc
    })


@app.route("/stream-logs")
def stream_logs():
    def event_stream():
        # SSE / text/event-stream
        while True:
            try:
                line = log_queue.get(timeout=0.5)
                # if special marker BOT_PROCESS_ENDED, still send
                yield f"data: {line}\n\n"
            except queue.Empty:
                # send keepalive comment to avoid SSE timeouts
                yield ": keepalive\n\n"
            except GeneratorExit:
                break
    return Response(event_stream(), mimetype="text/event-stream")


@app.route("/api/purchases", methods=["GET"])
def api_purchases():
    env = load_env_file()
    purchases_file = env.get("PURCHASES_FILE", PURCHASES_DEFAULT)
    if not os.path.exists(purchases_file):
        return jsonify({"ok": False, "error": "file_not_found", "path": purchases_file}), 404
    try:
        with open(purchases_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/download-purchases", methods=["GET"])
def download_purchases():
    env = load_env_file()
    purchases_file = env.get("PURCHASES_FILE", PURCHASES_DEFAULT)
    if not os.path.exists(purchases_file):
        return abort(404)
    return send_file(purchases_file, as_attachment=True)


# Static helper to load default template if .env missing
@app.route("/api/reset_template", methods=["POST"])
def api_reset_template():
    default = """# .env generated by web dashboard
UPBIT_ACCESS_KEY=
UPBIT_SECRET_KEY=
DRY_RUN=true
SIM_KRW_BALANCE=100000
INSTALLMENTS=5
MIN_KRW_ORDER=5000
TOTAL_INVEST_FRACTION=0.5
# TOTAL_INVEST_KRW=100000
ALLOCATIONS=KRW-BTC:50,KRW-ETH:30,KRW-XRP:20
DROP_PCT=2.0
DROP_PCT_PER_COIN=KRW-BTC:2,KRW-ETH:3,KRW-XRP:5
INITIAL_BUY=true
MONITOR_INTERVAL_MIN=5
TARGET_PROFIT_PCT=10
# TARGET_PROFIT_KRW=5000
SELL_FRACTION=1.0
PURCHASES_FILE=purchases.json
"""
    try:
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(default)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --- main ---
if __name__ == "__main__":
    # Ensure templates/static exist check isn't needed here - assume project structure
    app.run(host="0.0.0.0", port=5000, debug=True)