"""
RobloxOS Mock Data Generator
Symuluje dane z prawdziwej maszyny RobloxOS dla trybu demo na Replit.
"""

from __future__ import annotations

import random
import time
from datetime import datetime, date
from threading import Lock
from typing import Any


class MockDataGenerator:
    """Thread-safe generator symulowanych danych konsoli."""

    _APPS      = ["roblox", "discord", "browser", None]
    _APP_WEIGHTS = [55, 20, 15, 10]   # % szansy na każdy stan

    _LOG_TEMPLATES = [
        "[INFO]  Watchdog: skan zakończony, 0 nieautoryzowanych procesów.",
        "[INFO]  Launcher: aplikacja '{app}' uruchomiona przez robloxuser.",
        "[INFO]  Session: roblox – {used}min użyte z {limit}min limitu.",
        "[INFO]  OTA: sprawdzam aktualizacje... brak nowych commitów.",
        "[INFO]  Watchdog: procesy OK – sober({pid1}), discord({pid2}), Xorg({pid3})",
        "[OK]    AppArmor: profil robloxos.launcher aktywny (enforce).",
        "[INFO]  LightDM: sesja robloxuser aktywna od {uptime}.",
        "[INFO]  Network: ping 8.8.8.8 = {ping}ms",
        "[INFO]  Session: czas sesji zaktualizowany → roblox: {used}s",
        "[WARNING] Session: zbliża się limit dla 'roblox' – {rem} min pozostało.",
    ]

    def __init__(self) -> None:
        self._lock          = Lock()
        self._start_time    = time.time()
        self._session_start = time.time()
        self._base_session  = {"roblox": 4980, "discord": 1200, "browser": 600}
        self._active_app    = "roblox"
        self._fps_val       = 58
        self._ping_val      = 32
        self._log_buffer: list[str] = []
        self._log_counter   = 0

        # Wstępnie wypełnij bufor logów
        for _ in range(30):
            self._log_buffer.append(self._make_log_line())

    # ── Public API ──────────────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return self._build_status()

    def get_logs(self, n: int = 50) -> list[str]:
        with self._lock:
            return list(self._log_buffer[-n:])

    def new_log_line(self) -> str:
        """Generuje jedną nową linię logu (do push przez SocketIO)."""
        with self._lock:
            line = self._make_log_line()
            self._log_buffer.append(line)
            if len(self._log_buffer) > 500:
                self._log_buffer.pop(0)
            return line

    def tick(self) -> None:
        """Wywołuj co ~2s żeby symulacja była realistyczna."""
        with self._lock:
            elapsed = time.time() - self._session_start
            # FPS: oscyluje między 45-62 z małym szumem
            self._fps_val  = int(54 + 8 * math.sin(elapsed / 30) + random.randint(-3, 3))
            self._fps_val  = max(30, min(62, self._fps_val))
            # Ping: oscyluje 18-65ms
            self._ping_val = int(35 + 22 * math.sin(elapsed / 45) + random.randint(-5, 5))
            self._ping_val = max(18, min(120, self._ping_val))

    # ── Internal builders ───────────────────────────────────────────────────────

    def _elapsed_session(self) -> int:
        return int(time.time() - self._session_start)

    def _build_status(self) -> dict[str, Any]:
        elapsed = self._elapsed_session()
        limits  = {"roblox": 120, "discord": 60, "browser": 30}

        sessions: dict[str, Any] = {}
        for app in ("roblox", "discord", "browser"):
            base  = self._base_session[app]
            used  = base + (elapsed if app == "roblox" else 0)
            limit = limits[app] * 60
            rem   = max(0, limit - used)
            h, m  = divmod(used // 60, 60)
            sessions[app] = {
                "used_sec":  used,
                "used_str":  f"{h}h {m:02d}m",
                "limit_min": limits[app],
                "remaining": rem,
                "pct":       min(100, int(used / limit * 100)) if limit else 0,
            }

        uptime_h = int(elapsed / 3600) + 3
        uptime_m = int((elapsed % 3600) / 60) + 17
        ram_used = 1240 + random.randint(-50, 120)

        return {
            "cpu_pct":   round(18 + 12 * abs(math.sin(elapsed / 20)) + random.uniform(-3, 3), 1),
            "ram_pct":   round(ram_used / 8192 * 100, 1),
            "ram_used":  f"{ram_used} MB",
            "ram_total": "8192 MB",
            "disk_pct":  42,
            "disk_free": "17 GB",
            "uptime":    f"{uptime_h}h {uptime_m}m",
            "services":  {
                "watchdog": "active",
                "lightdm":  "active",
                "apparmor": "active",
                "webpanel": "active",
            },
            "sessions":      sessions,
            "session_date":  str(date.today()),
            "fps":           self._fps_val,
            "ping_ms":       self._ping_val,
            "active_app":    self._active_app,
        }

    def _make_log_line(self) -> str:
        self._log_counter += 1
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tmpl = random.choice(self._LOG_TEMPLATES)
        line = tmpl.format(
            app    = random.choice(["roblox", "discord", "chromium"]),
            used   = random.randint(40, 115),
            limit  = 120,
            pid1   = random.randint(1000, 9999),
            pid2   = random.randint(1000, 9999),
            pid3   = random.randint(1000, 9999),
            uptime = f"{random.randint(1,5)}h {random.randint(0,59)}m",
            ping   = random.randint(18, 65),
            rem    = random.randint(3, 25),
        )
        return f"{ts} {line}"


# Lazy import math (żeby nie crashować przy importach)
import math

# Singleton dostępny globalnie
_generator: MockDataGenerator | None = None


def get_generator() -> MockDataGenerator:
    global _generator
    if _generator is None:
        _generator = MockDataGenerator()
    return _generator
