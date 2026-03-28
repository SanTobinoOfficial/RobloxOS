#!/usr/bin/env python3
"""
RobloxOS Web Control Panel – Replit Edition
Działanie: python3 app.py  (Replit uruchamia automatycznie)

Pierwsze uruchomienie: konto admin/admin123 tworzone automatycznie.
Zmień hasło natychmiast po zalogowaniu!
"""

from __future__ import annotations

import json
import logging
import os
import random
import secrets
import time
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Generator

import bcrypt
from flask import (
    Flask, Response, jsonify, redirect, render_template,
    request, session, stream_with_context, url_for,
)

# ── Replit detection ────────────────────────────────────────────────────────
# Replit zawsze ustawia zmienną REPL_ID; można też wymusić REPLIT_MODE=true
REPLIT_MODE: bool = bool(
    os.getenv("REPL_ID") or os.getenv("REPLIT_MODE", "").lower() == "true"
)

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE  = DATA_DIR / "session_times.json"
LOGS_DIR    = DATA_DIR / "logs"
LOG_FILES   = {
    "watchdog": LOGS_DIR / "watchdog.log",
    "ota":      LOGS_DIR / "ota.log",
    "setup":    LOGS_DIR / "setup.log",
    "session":  LOGS_DIR / "session.log",
}

# ── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("webpanel")

# Cache danych z prawdziwej maszyny (POST /api/update)
_real_data: dict[str, Any] = {}

# ── Config defaults ──────────────────────────────────────────────────────────
_CONFIG_DEFAULTS: dict[str, Any] = {
    "admin_password_hash":  "",
    "force_password_change": False,
    "api_token":            "",
    "whitelist":            ["roblox.com", "discord.com", "youtube.com"],
    "time_limits":          {"roblox": 120, "discord": 60, "browser": 30},
    "schedule":             {"enabled": False, "days": list(range(7)), "start": "15:00", "end": "21:00"},
    "ota":                  {"enabled": False, "repo_url": "", "check_time": "03:00"},
    "vm_mode":              False,
    "apparmor_mode":        "enforce",
    "notifications":        {"email": "", "webhook": ""},
}

# ── Config helpers ───────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        data = json.loads(CONFIG_FILE.read_text())
        return {**_CONFIG_DEFAULTS, **data}
    except (OSError, json.JSONDecodeError):
        return dict(_CONFIG_DEFAULTS)


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"roblox": 0, "discord": 0, "browser": 0, "date": ""}


# ── Bootstrap (pierwsze uruchomienie) ────────────────────────────────────────

def _bootstrap() -> None:
    """Tworzy strukturę katalogów i domyślne konto przy pierwszym uruchomieniu."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        cfg = dict(_CONFIG_DEFAULTS)
        cfg["admin_password_hash"]  = _hash_password("admin123")
        cfg["force_password_change"] = True
        cfg["api_token"]            = secrets.token_hex(32)
        save_config(cfg)
        log.info("=" * 60)
        log.info("PIERWSZE URUCHOMIENIE: konto admin/admin123 utworzone.")
        log.info("Zaloguj się i NATYCHMIAST zmień hasło!")
        log.info("=" * 60)


# ── Auth helpers ─────────────────────────────────────────────────────────────

def _check_password(plain: str) -> bool:
    cfg = load_config()
    hashed = cfg.get("admin_password_hash", "")
    if not hashed:
        return False
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# ── Context processor ────────────────────────────────────────────────────────

@app.context_processor
def _inject_globals() -> dict:
    """Wstrzykuje demo_mode i real_mode do wszystkich szablonów."""
    fresh_real = bool(_real_data) and time.time() - _real_data.get("_ts", 0) < 90
    return {
        "demo_mode": REPLIT_MODE and not fresh_real,
        "real_mode": fresh_real,   # maszyna wysyła dane na żywo
    }


# ── Status helpers ───────────────────────────────────────────────────────────

def _get_display_status() -> dict:
    """Zwraca dane do wyświetlenia: realne (maszyna) → mock → psutil."""
    if _real_data and time.time() - _real_data.get("_ts", 0) < 90:
        return _build_status_from_push(_real_data)
    if REPLIT_MODE:
        from mock_data import get_generator
        return get_generator().get_status()
    return _get_system_status()


def _build_status_from_push(data: dict) -> dict:
    """Buduje pełny status dict z danych przesłanych przez POST /api/update."""
    from mock_data import get_generator
    base = get_generator().get_status()          # wypełnia brakujące pola
    limits_min = load_config().get("time_limits", {"roblox": 120, "discord": 60, "browser": 30})
    active_key = (data.get("active_app") or "").lower()
    session_time = int(data.get("session_time", 0))

    for app_key in ("roblox", "discord", "browser"):
        used  = session_time if app_key == active_key else 0
        limit = int(limits_min.get(app_key, 120)) * 60
        h, m  = divmod(used // 60, 60)
        base["sessions"][app_key] = {
            "used_sec":  used,
            "used_str":  f"{h}h {m:02d}m",
            "limit_min": limits_min.get(app_key, 120),
            "remaining": max(0, limit - used),
            "pct":       min(100, int(used / limit * 100)) if limit else 0,
        }

    base["fps"]        = int(data.get("fps",    base["fps"]))
    base["ping_ms"]    = int(data.get("ping",   base["ping_ms"]))
    ram_mb = int(data.get("ram_mb", 1240))
    base["ram_used"]   = f"{ram_mb} MB"
    base["ram_pct"]    = round(ram_mb / 8192 * 100, 1)
    base["active_app"] = active_key
    return base


def _get_system_status() -> dict:
    """Status oparty o psutil – tylko dla prawdziwej maszyny RobloxOS."""
    import psutil, subprocess

    cpu  = psutil.cpu_percent(interval=0.3)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    uptime_sec = int(datetime.now().timestamp() - psutil.boot_time())
    h, rem = divmod(uptime_sec, 3600)
    m = rem // 60

    state  = load_state()
    cfg    = load_config()
    limits = cfg.get("time_limits", {})
    sessions: dict = {}
    for app_key in ("roblox", "discord", "browser"):
        used  = int(state.get(app_key, 0))
        limit = int(limits.get(app_key, 0)) * 60
        sessions[app_key] = {
            "used_sec":  used,
            "used_str":  f"{used // 3600}h {(used % 3600) // 60}m",
            "limit_min": limits.get(app_key, 0),
            "remaining": max(0, limit - used) if limit else None,
            "pct":       min(100, int(used / limit * 100)) if limit else 0,
        }

    def _svc(name: str) -> str:
        try:
            r = subprocess.run(["systemctl", "is-active", name],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip()
        except Exception:
            return "unknown"

    return {
        "cpu_pct":    cpu,
        "ram_pct":    mem.percent,
        "ram_used":   f"{mem.used // (1024**2)} MB",
        "ram_total":  f"{mem.total // (1024**2)} MB",
        "disk_pct":   disk.percent,
        "disk_free":  f"{disk.free // (1024**3)} GB",
        "uptime":     f"{h}h {m}m",
        "services": {
            "watchdog": _svc("robloxos-watchdog"),
            "lightdm":  _svc("lightdm"),
            "apparmor": _svc("apparmor"),
            "webpanel": _svc("robloxos-webpanel"),
        },
        "sessions":      sessions,
        "session_date":  state.get("date", "—"),
        "fps":           0,
        "ping_ms":       0,
        "active_app":    "",
    }


def _get_active_app() -> str:
    if REPLIT_MODE:
        from mock_data import get_generator
        return get_generator().get_status()["active_app"]
    import psutil
    checks = [("roblox", ["sober", "robloxplayer"]),
              ("discord", ["discord"]),
              ("browser", ["chromium"])]
    for app_key, patterns in checks:
        for proc in psutil.process_iter(["name"]):
            try:
                if any(p in proc.info["name"].lower() for p in patterns):
                    return app_key
            except Exception:
                pass
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES – AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def login_page():
    cfg        = load_config()
    first_run  = cfg.get("force_password_change", False)
    error      = None

    if request.method == "POST":
        if _check_password(request.form.get("password", "")):
            session["authenticated"] = True
            session.permanent        = False
            log.info(f"Udane logowanie z {request.remote_addr}")
            if cfg.get("force_password_change"):
                return redirect(url_for("change_password_page"))
            return redirect(url_for("dashboard"))
        error = "Nieprawidłowe hasło."
        log.warning(f"Nieudane logowanie z {request.remote_addr}")

    return render_template("login.html", error=error, first_run=first_run)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password_page():
    msg   = None
    error = None

    if request.method == "POST":
        old_pw  = request.form.get("old_password", "")
        new_pw  = request.form.get("new_password", "")
        new_pw2 = request.form.get("new_password2", "")

        if not _check_password(old_pw):
            error = "Nieprawidłowe obecne hasło."
        elif len(new_pw) < 8:
            error = "Nowe hasło musi mieć co najmniej 8 znaków."
        elif new_pw != new_pw2:
            error = "Nowe hasła nie są zgodne."
        elif new_pw == "admin123":
            error = "Nie możesz użyć domyślnego hasła admin123."
        else:
            cfg = load_config()
            cfg["admin_password_hash"]   = _hash_password(new_pw)
            cfg["force_password_change"] = False
            save_config(cfg)
            msg = "Hasło zmienione pomyślnie."
            log.info(f"Hasło zmienione przez {request.remote_addr}")

    return render_template("change_password.html", msg=msg, error=error)


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES – PAGES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
@login_required
def dashboard():
    status    = _get_display_status()
    active    = status.get("active_app", "")
    cfg       = load_config()
    has_real  = bool(_real_data) and time.time() - _real_data.get("_ts", 0) < 90
    return render_template("dashboard.html", status=status, active=active,
                           cfg=cfg, has_real_data=has_real)


@app.route("/whitelist", methods=["GET", "POST"])
@login_required
def whitelist_page():
    cfg = load_config()
    msg = None

    if request.method == "POST":
        action = request.form.get("action")
        domain = request.form.get("domain", "").strip().lower()

        if action == "add" and domain:
            if domain not in cfg["whitelist"]:
                cfg["whitelist"].append(domain)
                save_config(cfg)
                if not REPLIT_MODE:
                    _update_browser_rules(cfg["whitelist"])
                msg = f"Dodano: {domain}"
                log.info(f"Whitelist: dodano {domain}")
            else:
                msg = f"{domain} już na liście."
        elif action == "remove" and domain:
            cfg["whitelist"] = [d for d in cfg["whitelist"] if d != domain]
            save_config(cfg)
            if not REPLIT_MODE:
                _update_browser_rules(cfg["whitelist"])
            msg = f"Usunięto: {domain}"
            log.info(f"Whitelist: usunięto {domain}")

    return render_template("whitelist.html", cfg=cfg, msg=msg)


@app.route("/timelimits", methods=["GET", "POST"])
@login_required
def timelimits_page():
    cfg = load_config()
    msg = None

    if request.method == "POST":
        try:
            cfg["time_limits"] = {
                "roblox":  int(request.form.get("roblox",  120)),
                "discord": int(request.form.get("discord",  60)),
                "browser": int(request.form.get("browser",  30)),
            }
            cfg["schedule"] = {
                "enabled": request.form.get("sched_enabled") == "on",
                "days":    [int(d) for d in request.form.getlist("days")],
                "start":   request.form.get("start_time", "15:00"),
                "end":     request.form.get("end_time",   "21:00"),
            }
            save_config(cfg)
            msg = "Limity zaktualizowane."
            log.info("Limity czasu zaktualizowane.")
        except (ValueError, KeyError) as exc:
            msg = f"Błąd: {exc}"

    return render_template("timelimits.html", cfg=cfg, msg=msg)


@app.route("/logs")
@login_required
def logs_page():
    log_name = request.args.get("log", "watchdog")
    if log_name not in LOG_FILES:
        log_name = "watchdog"

    if REPLIT_MODE:
        from mock_data import get_generator
        lines = get_generator().get_logs(200)
    else:
        try:
            lines = LOG_FILES[log_name].read_text().splitlines()[-200:]
        except OSError:
            lines = [f"(Plik {LOG_FILES[log_name]} nie istnieje lub jest niedostępny)"]

    return render_template("logs.html", lines=lines, log_name=log_name,
                           log_files=list(LOG_FILES.keys()))


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES – API
# ══════════════════════════════════════════════════════════════════════════════

def _demo_ok(msg: str = "Akcja zasymulowana (tryb demo).") -> Response:
    return jsonify({"ok": True, "demo": True, "msg": msg})


@app.route("/api/status")
@login_required
def api_status():
    return jsonify(_get_display_status())


@app.route("/api/active-app")
@login_required
def api_active_app():
    return jsonify({"app": _get_active_app()})


@app.route("/api/session/reset", methods=["POST"])
@login_required
def api_session_reset():
    if REPLIT_MODE:
        return _demo_ok("Reset licznika sesji zasymulowany.")
    import subprocess, sys
    app_key = (request.get_json(silent=True) or {}).get("app")
    try:
        cmd = [sys.executable, "/home/robloxuser/launcher/session_timer.py", "reset"]
        if app_key:
            cmd.append(app_key)
        subprocess.run(cmd, timeout=5)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/service/<name>", methods=["POST"])
@login_required
def api_service(name: str):
    if REPLIT_MODE:
        return _demo_ok(f"Restart usługi '{name}' zasymulowany.")
    import subprocess
    allowed = {"robloxos-watchdog", "lightdm", "robloxos-webpanel", "apparmor"}
    if name not in allowed:
        return jsonify({"error": "Niedozwolona usługa"}), 403
    action = (request.get_json(silent=True) or {}).get("action", "restart")
    if action not in ("start", "stop", "restart"):
        return jsonify({"error": "Niedozwolona akcja"}), 400
    try:
        subprocess.run(["systemctl", action, name], timeout=10, check=True)
        return jsonify({"ok": True, "service": name, "action": action})
    except subprocess.CalledProcessError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/system/restart", methods=["POST"])
@login_required
def api_restart():
    if REPLIT_MODE:
        return _demo_ok("Restart systemu zasymulowany.")
    import subprocess
    subprocess.Popen(["shutdown", "-r", "now"])
    return jsonify({"ok": True, "msg": "System restartuje się..."})


@app.route("/api/system/shutdown", methods=["POST"])
@login_required
def api_shutdown():
    if REPLIT_MODE:
        return _demo_ok("Shutdown systemu zasymulowany.")
    import subprocess
    subprocess.Popen(["shutdown", "-h", "now"])
    return jsonify({"ok": True, "msg": "System wyłącza się..."})


@app.route("/api/launcher/restart", methods=["POST"])
@login_required
def api_launcher_restart():
    if REPLIT_MODE:
        return _demo_ok("Restart launchera zasymulowany.")
    import subprocess
    try:
        subprocess.run(["pkill", "-f", "launcher.py"], timeout=5)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/logs/stream")
@login_required
def api_logs_stream():
    """SSE: live tail logów. W trybie Replit – dane z mock generatora."""
    log_name = request.args.get("log", "watchdog")

    if REPLIT_MODE:
        def _mock() -> Generator[str, None, None]:
            from mock_data import get_generator
            gen = get_generator()
            try:
                while True:
                    line = gen.new_log_line()
                    yield f"data: {json.dumps(line)}\n\n"
                    time.sleep(random.uniform(1.5, 4.0))
            except GeneratorExit:
                return
        return Response(stream_with_context(_mock()), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    if log_name not in LOG_FILES:
        return jsonify({"error": "Nieznany log"}), 400

    def _tail() -> Generator[str, None, None]:
        try:
            with open(LOG_FILES[log_name]) as f:
                f.seek(0, 2)
                while True:
                    line = f.readline()
                    if line:
                        yield f"data: {json.dumps(line.rstrip())}\n\n"
                    else:
                        time.sleep(0.5)
        except (OSError, GeneratorExit):
            return

    return Response(stream_with_context(_tail()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/whitelist/export")
@login_required
def api_whitelist_export():
    cfg = load_config()
    return jsonify({"whitelist": cfg["whitelist"], "exported_at": datetime.now().isoformat()})


# ── Endpoint dla prawdziwej maszyny RobloxOS ─────────────────────────────────

@app.route("/api/update", methods=["POST"])
def api_machine_update():
    """
    Przyjmuje dane z prawdziwej maszyny RobloxOS co ~30s.
    Nagłówek: X-RobloxOS-Token: <token z config.json>
    Body JSON: {session_time, active_app, fps, ping, ram_mb}
    """
    token    = request.headers.get("X-RobloxOS-Token", "")
    cfg      = load_config()
    expected = cfg.get("api_token", "")

    if not expected or token != expected:
        log.warning(f"Nieautoryzowana próba /api/update z {request.remote_addr}")
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(force=True, silent=True) or {}
    data["_ts"] = time.time()
    _real_data.update(data)
    log.info(f"Dane maszyny: app={data.get('active_app')} fps={data.get('fps')} ping={data.get('ping')}")
    return jsonify({"ok": True, "received_at": datetime.now().isoformat()})


@app.route("/api/token")
@login_required
def api_token_info():
    """Zwraca token API i endpoint do konfiguracji maszyny RobloxOS."""
    cfg = load_config()
    return jsonify({
        "api_token":  cfg.get("api_token", ""),
        "endpoint":   request.url_root.rstrip("/") + "/api/update",
        "header":     "X-RobloxOS-Token",
    })


# ── Browser rules sync (tylko na prawdziwej maszynie) ────────────────────────

BROWSER_RULES_PATH = Path("/home/robloxuser/browser/rules.json")


def _update_browser_rules(whitelist: list[str]) -> None:
    rules = []
    for i, domain in enumerate(whitelist, 1):
        rules.append({
            "id": i, "priority": 10, "action": {"type": "allow"},
            "condition": {"requestDomains": [domain],
                          "resourceTypes": ["main_frame", "sub_frame"]},
        })
    rules.append({
        "id": 999, "priority": 1,
        "action": {"type": "redirect", "redirect": {"extensionPath": "/blocked.html"}},
        "condition": {"regexFilter": "^https?://.*", "resourceTypes": ["main_frame"]},
    })
    try:
        BROWSER_RULES_PATH.write_text(json.dumps(rules, indent=2))
        log.info(f"rules.json zaktualizowany ({len(whitelist)} domen).")
    except OSError as exc:
        log.error(f"Nie można zaktualizować rules.json: {exc}")


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    _bootstrap()
    port = int(os.getenv("PORT", 8080))
    log.info(f"RobloxOS Web Panel (Replit Edition) – http://0.0.0.0:{port}")
    log.info(f"REPLIT_MODE = {REPLIT_MODE}")
    if REPLIT_MODE:
        cfg = load_config()
        log.info(f"Token API dla maszyny: {cfg.get('api_token', '—')[:16]}...")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
