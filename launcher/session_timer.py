#!/usr/bin/env python3
"""
RobloxOS Session Timer
Śledzi czas aktywnej sesji każdej aplikacji i zapisuje stan do JSON.
Uruchamiany jako osobny proces przez systemd lub importowany przez launcher.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import psutil

# ── Config ─────────────────────────────────────────────────────────────────────
STATE_FILE  = Path("/var/lib/robloxos/session_times.json")
CONFIG_FILE = Path("/etc/robloxos/config.json")
LOG_FILE    = Path("/var/log/robloxos-session.log")
TICK_SEC    = 10   # jak często zapisujemy stan

# Mapowanie klucza aplikacji → wzorce nazw procesów (lowercase)
APP_PROCESS_MAP: dict[str, list[str]] = {
    "roblox":  ["sober", "robloxplayer", "roblox"],
    "discord": ["discord"],
    "browser": ["chromium", "chromium-browser"],
}

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("session-timer")

# ── State ──────────────────────────────────────────────────────────────────────

class SessionState:
    """Persistent session state backed by a JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
            # Reset if date changed (new day)
            saved_date = raw.get("date", "")
            today = str(date.today())
            if saved_date != today:
                log.info(f"Nowy dzień ({today}) – resetuję liczniki.")
                self._data = {
                    "roblox": 0, "discord": 0, "browser": 0, "date": today
                }
            else:
                self._data = raw
        except (OSError, json.JSONDecodeError):
            self._data = {
                "roblox": 0, "discord": 0, "browser": 0, "date": str(date.today())
            }

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2))
        except OSError as exc:
            log.warning(f"Nie można zapisać stanu sesji: {exc}")

    def add(self, app_key: str, seconds: int) -> None:
        self._data[app_key] = int(self._data.get(app_key, 0)) + seconds

    def get(self, app_key: str) -> int:
        return int(self._data.get(app_key, 0))

    def reset(self, app_key: Optional[str] = None) -> None:
        if app_key:
            self._data[app_key] = 0
        else:
            for k in ("roblox", "discord", "browser"):
                self._data[k] = 0
        self.save()
        log.info(f"Reset licznika: {app_key or 'ALL'}")

    @property
    def date_key(self) -> str:
        return str(self._data.get("date", ""))


# ── Process detection ──────────────────────────────────────────────────────────

def _detect_active_app() -> Optional[str]:
    """Return the key of the first running whitelisted app, or None."""
    try:
        for proc in psutil.process_iter(["name", "status"]):
            pname = proc.info["name"].lower()
            if proc.info["status"] == psutil.STATUS_ZOMBIE:
                continue
            for app_key, patterns in APP_PROCESS_MAP.items():
                if any(pat in pname for pat in patterns):
                    return app_key
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return None


def _load_limits() -> dict[str, int]:
    """Load time limits (minutes) from config."""
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
        return cfg.get("time_limits", {})
    except (OSError, json.JSONDecodeError):
        return {"roblox": 120, "discord": 60, "browser": 30}


# ── Main loop ──────────────────────────────────────────────────────────────────

class SessionTimer:
    """Main session tracking daemon."""

    def __init__(self) -> None:
        self.state  = SessionState(STATE_FILE)
        self._running = True
        self._last_reset_day: str = str(date.today())

    def run(self) -> None:
        log.info("Session Timer uruchomiony.")
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT,  self._shutdown)

        while self._running:
            try:
                self._tick()
            except Exception as exc:
                log.error(f"Błąd w tick: {exc}")
            time.sleep(TICK_SEC)

        self.state.save()
        log.info("Session Timer zatrzymany.")

    def _tick(self) -> None:
        today = str(date.today())

        # Midnight reset
        if today != self._last_reset_day:
            self.state.reset()
            self._last_reset_day = today

        active = _detect_active_app()
        if active is None:
            return

        self.state.add(active, TICK_SEC)
        used_sec = self.state.get(active)
        limits   = _load_limits()
        limit_sec = limits.get(active, 0) * 60

        if limit_sec > 0:
            remaining = limit_sec - used_sec
            if remaining <= 0:
                log.warning(
                    f"Limit wyczerpany dla '{active}' "
                    f"(użyte: {used_sec//60}min, limit: {limit_sec//60}min)"
                )
                self._notify_limit(active)
            elif remaining <= 300:  # 5 minut
                log.info(f"Zbliża się limit dla '{active}' – {remaining}s pozostało.")

        # Zapisz stan co TICK_SEC sekund
        self.state.save()

    def _notify_limit(self, app_key: str) -> None:
        """Write a notification flag that launcher.py can poll."""
        flag = Path("/tmp/robloxos_limit_reached")
        flag.write_text(app_key)

    def _shutdown(self, _sig: int, _frame) -> None:
        self._running = False


# ── CLI interface ──────────────────────────────────────────────────────────────

def _cli_status() -> None:
    state = SessionState(STATE_FILE)
    limits = _load_limits()
    print(f"Data: {state.date_key}")
    print(f"{'Aplikacja':<12} {'Użyte':>10} {'Limit':>10} {'Pozostało':>12}")
    print("-" * 48)
    for app in ("roblox", "discord", "browser"):
        used  = state.get(app)
        lim   = limits.get(app, 0) * 60
        rem   = max(0, lim - used) if lim else -1
        u_str = f"{used//3600}h {(used%3600)//60}m"
        l_str = f"{lim//60}m" if lim else "∞"
        r_str = f"{rem//60}m" if rem >= 0 else "∞"
        print(f"{app:<12} {u_str:>10} {l_str:>10} {r_str:>12}")


def _cli_reset(app_key: Optional[str]) -> None:
    state = SessionState(STATE_FILE)
    state.reset(app_key)
    print(f"Zresetowano: {app_key or 'wszystkie'}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RobloxOS Session Timer")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run",    help="Uruchom daemon")
    sub.add_parser("status", help="Pokaż status sesji")
    reset_p = sub.add_parser("reset", help="Resetuj licznik")
    reset_p.add_argument("app", nargs="?", choices=["roblox","discord","browser"])
    args = parser.parse_args()

    if args.cmd == "run":
        SessionTimer().run()
    elif args.cmd == "status":
        _cli_status()
    elif args.cmd == "reset":
        _cli_reset(getattr(args, "app", None))
    else:
        parser.print_help()
