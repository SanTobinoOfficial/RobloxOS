#!/usr/bin/env python3
"""
RobloxOS → Replit Sync Daemon
Wysyła dane systemu do panelu Replit co 30 sekund.

Uruchomienie:
    sudo python3 sync_to_replit.py

Jako systemd service (patrz sync.service):
    sudo systemctl start robloxos-sync
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import psutil
import requests

# ── Konfiguracja ─────────────────────────────────────────────────────────────
CONFIG_FILE  = Path("/etc/robloxos/config.json")
STATE_FILE   = Path("/var/lib/robloxos/session_times.json")
LOG_FILE     = Path("/var/log/robloxos-sync.log")
SYNC_INTERVAL = 30          # sekundy między wysyłkami
REQUEST_TIMEOUT = 10        # timeout pojedynczego requestu (s)
MAX_RETRIES   = 3           # ile razy powtórzyć przy błędzie sieci
RETRY_DELAY   = 5           # sekund między retries

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

handler = RotatingFileHandler(
    LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

log = logging.getLogger("robloxos-sync")
log.setLevel(logging.INFO)
log.addHandler(handler)
log.addHandler(logging.StreamHandler(sys.stdout))

# ── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Wczytuje konfigurację z /etc/robloxos/config.json."""
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.error(f"Nie można wczytać config.json: {exc}")
        return {}


def load_state() -> dict:
    """Wczytuje czasy sesji z /var/lib/robloxos/session_times.json."""
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"roblox": 0, "discord": 0, "browser": 0, "date": ""}


def get_replit_config(cfg: dict) -> tuple[str, str]:
    """Zwraca (url, token) z config.json lub zmiennych środowiskowych."""
    url   = os.getenv("REPLIT_URL")   or cfg.get("replit_url",   "")
    token = os.getenv("REPLIT_TOKEN") or cfg.get("replit_token", "")
    return url.rstrip("/"), token


# ── Zbieranie danych ──────────────────────────────────────────────────────────

def get_active_app() -> str:
    """Wykrywa aktywną aplikację przez listę procesów."""
    checks = [
        ("roblox",  ["sober", "robloxplayer", "roblox"]),
        ("discord", ["discord"]),
        ("browser", ["chromium", "chromium-browser", "firefox"]),
    ]
    try:
        for app_key, patterns in checks:
            for proc in psutil.process_iter(["name", "cmdline"]):
                try:
                    name = (proc.info["name"] or "").lower()
                    if any(p in name for p in patterns):
                        return app_key
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
    except Exception as exc:
        log.debug(f"Błąd wykrywania aplikacji: {exc}")
    return ""


def get_ping_ms() -> int:
    """Zwraca ping do 8.8.8.8 w milisekundach (0 jeśli błąd)."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "3", "8.8.8.8"],
            capture_output=True, text=True, timeout=5,
        )
        # Szukaj "time=12.3 ms" lub "time=12.3ms"
        for part in result.stdout.split():
            if part.startswith("time="):
                return int(float(part.split("=")[1]))
    except Exception:
        pass
    return 0


def get_fps() -> int:
    """
    Próbuje odczytać FPS Roblox z pliku logu Sobera.
    Jeśli niedostępne – zwraca 0.
    """
    sober_log = Path("/home/robloxuser/.local/share/sober/last_run.log")
    if not sober_log.exists():
        return 0
    try:
        # Szukaj ostatniej linii z FPS w ostatnich 50 liniach logu
        lines = sober_log.read_text(errors="replace").splitlines()[-50:]
        for line in reversed(lines):
            line_lower = line.lower()
            if "fps" in line_lower:
                # Typowy format: "FPS: 60" lub "[FPS] 58.2"
                for token in line.split():
                    token = token.strip("[]():,")
                    try:
                        val = float(token)
                        if 1 <= val <= 300:
                            return int(val)
                    except ValueError:
                        pass
    except Exception:
        pass
    return 0


def collect_data() -> dict[str, Any]:
    """Zbiera wszystkie dane do wysłania do panelu."""
    state      = load_state()
    active_app = get_active_app()
    mem        = psutil.virtual_memory()

    session_time = int(state.get(active_app, 0)) if active_app else 0

    data: dict[str, Any] = {
        "active_app":   active_app,
        "session_time": session_time,
        "ram_mb":       mem.used // (1024 ** 2),
        "fps":          get_fps(),
        "ping":         get_ping_ms(),
        "timestamp":    datetime.now().isoformat(),
    }

    log.debug(
        f"Zebrane dane: app={active_app!r} "
        f"sesja={session_time}s "
        f"fps={data['fps']} ping={data['ping']}ms "
        f"ram={data['ram_mb']}MB"
    )
    return data


# ── Wysyłanie danych ──────────────────────────────────────────────────────────

def send_data(url: str, token: str, data: dict) -> bool:
    """
    Wysyła dane do panelu Replit.
    Próbuje MAX_RETRIES razy przy błędach sieci.
    Zwraca True przy sukcesie.
    """
    endpoint = f"{url}/api/update"
    headers  = {
        "X-RobloxOS-Token": token,
        "Content-Type":     "application/json",
        "User-Agent":       "RobloxOS-Sync/1.0",
    }

    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                endpoint, json=data, headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                log.info(
                    f"Dane wysłane: app={data.get('active_app')!r} "
                    f"sesja={data.get('session_time')}s "
                    f"fps={data.get('fps')} ping={data.get('ping')}ms"
                )
                return True
            elif resp.status_code == 401:
                log.error("Token API nieprawidłowy (401). Sprawdź config lub uruchom setup ponownie.")
                return False   # nie ponawiaj przy błędzie auth
            else:
                log.warning(f"Nieoczekiwany status {resp.status_code} (próba {attempt}/{MAX_RETRIES})")
                last_error = Exception(f"HTTP {resp.status_code}")

        except requests.exceptions.ConnectionError as exc:
            log.warning(f"Brak połączenia z {url} (próba {attempt}/{MAX_RETRIES}): {exc}")
            last_error = exc
        except requests.exceptions.Timeout:
            log.warning(f"Timeout po {REQUEST_TIMEOUT}s (próba {attempt}/{MAX_RETRIES})")
            last_error = Exception("timeout")
        except Exception as exc:
            log.error(f"Nieoczekiwany błąd wysyłania: {exc}")
            return False

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)

    log.error(f"Nie udało się wysłać danych po {MAX_RETRIES} próbach. Ostatni błąd: {last_error}")
    return False


# ── Główna pętla ──────────────────────────────────────────────────────────────

def main() -> None:
    log.info("=" * 56)
    log.info("RobloxOS Sync Daemon – start")
    log.info(f"Config:   {CONFIG_FILE}")
    log.info(f"Interval: {SYNC_INTERVAL}s")
    log.info("=" * 56)

    # Wczytaj konfigurację raz na start; przeładowuj przy każdym cyklu
    # (żeby zmiany w config.json były widoczne bez restartu usługi)
    consecutive_errors = 0

    while True:
        cycle_start = time.monotonic()

        try:
            cfg           = load_config()
            replit_url, replit_token = get_replit_config(cfg)

            if not replit_url or not replit_token:
                log.error(
                    "Brak replit_url lub replit_token w config.json. "
                    "Uruchom: sudo bash remote/setup_replit_sync.sh"
                )
                # Czekaj dłużej żeby nie zaśmiecać logów
                time.sleep(SYNC_INTERVAL * 2)
                continue

            data    = collect_data()
            success = send_data(replit_url, replit_token, data)

            if success:
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                if consecutive_errors >= 10:
                    log.error(
                        f"{consecutive_errors} kolejnych błędów. "
                        "Sprawdź połączenie internetowe i status panelu Replit."
                    )

        except KeyboardInterrupt:
            log.info("Sync zatrzymany przez użytkownika (Ctrl+C).")
            break
        except Exception as exc:
            log.error(f"Nieoczekiwany błąd w głównej pętli: {exc}", exc_info=True)
            consecutive_errors += 1

        # Dokładny interwał (odejmujemy czas wykonania cyklu)
        elapsed = time.monotonic() - cycle_start
        sleep_time = max(0, SYNC_INTERVAL - elapsed)
        time.sleep(sleep_time)

    log.info("RobloxOS Sync Daemon – zatrzymany.")


if __name__ == "__main__":
    main()
