#!/usr/bin/env python3
"""
RobloxOS Stats Overlay
Minimalistyczny widget always-on-top z FPS, ping, RAM i timerem sesji.
Ctrl+Shift+S = pokaż/ukryj.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import psutil
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QBrush, QPen, QKeySequence
from PyQt6.QtWidgets import (
    QApplication, QLabel, QShortcut, QVBoxLayout, QWidget,
)

CONFIG_FILE = Path("/etc/robloxos/config.json")
STATE_FILE  = Path("/var/lib/robloxos/session_times.json")

# ── Ping worker ────────────────────────────────────────────────────────────────

class PingWorker(QThread):
    """Measures latency to 8.8.8.8 every 5 seconds."""

    result = pyqtSignal(int)   # ms, or -1 if timeout

    def __init__(self) -> None:
        super().__init__()
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                out = subprocess.check_output(
                    ["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                    stderr=subprocess.DEVNULL,
                    timeout=4,
                    text=True,
                )
                # Parse: "rtt min/avg/max/mdev = 12.345/12.345/12.345/0.000 ms"
                for line in out.splitlines():
                    if "rtt" in line or "round-trip" in line:
                        avg = float(line.split("/")[4])
                        self.result.emit(int(avg))
                        break
            except Exception:
                self.result.emit(-1)
            time.sleep(5)

    def stop(self) -> None:
        self._running = False


# ── RAM reader ─────────────────────────────────────────────────────────────────

def _get_roblox_ram_mb() -> Optional[int]:
    """Return RSS memory (MB) used by Roblox/Sober processes, or None."""
    patterns = ["sober", "robloxplayer", "discord", "chromium"]
    total = 0
    found = False
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = proc.info["name"].lower()
            if any(p in name for p in patterns):
                total += proc.info["memory_info"].rss
                found = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return total // (1024 * 1024) if found else None


# ── Session info ───────────────────────────────────────────────────────────────

def _get_session_info() -> tuple[str, str]:
    """Return (app_name, time_remaining_str)."""
    try:
        data   = json.loads(STATE_FILE.read_text())
        config = json.loads(CONFIG_FILE.read_text())
        limits = config.get("time_limits", {})

        for app, patterns in [
            ("roblox",  ["sober", "robloxplayer"]),
            ("discord", ["discord"]),
            ("browser", ["chromium"]),
        ]:
            if any(
                any(p in proc.info["name"].lower() for p in patterns)
                for proc in psutil.process_iter(["name"])
                if not proc.info.get("name", "")
            ):
                used  = int(data.get(app, 0))
                limit = int(limits.get(app, 0)) * 60
                if limit > 0:
                    rem = max(0, limit - used)
                    h, m = divmod(rem // 60, 60)
                    return app, f"{h}h{m:02d}m" if h else f"{m}m"
    except Exception:
        pass
    return "", ""


# ── Overlay widget ─────────────────────────────────────────────────────────────

class StatsOverlay(QWidget):
    """Semi-transparent always-on-top stats panel."""

    def __init__(self) -> None:
        super().__init__()

        # Window flags: no frame, always on top, no taskbar entry, transparent
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(180, 120)

        self._ping_ms: int = -1
        self._visible = True

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        font_mono = QFont("Ubuntu Mono", 11)
        font_mono.setBold(True)

        def _row(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setFont(font_mono)
            lbl.setStyleSheet("color: #ffffff; background: transparent;")
            return lbl

        self.fps_lbl     = _row("FPS:  —")
        self.ping_lbl    = _row("Ping: —")
        self.ram_lbl     = _row("RAM:  —")
        self.session_lbl = _row("Sesja: —")

        for lbl in (self.fps_lbl, self.ping_lbl, self.ram_lbl, self.session_lbl):
            layout.addWidget(lbl)

        # Position: top-right corner with margin
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 12, 12)

        # Ping worker
        self._ping_worker = PingWorker()
        self._ping_worker.result.connect(self._on_ping)
        self._ping_worker.start()

        # Refresh timer (every 2s)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

        # Toggle shortcut: Ctrl+Shift+S
        shortcut = QShortcut(QKeySequence("Ctrl+Shift+S"), self)
        shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        shortcut.activated.connect(self.toggle_visibility)

        self._refresh()

    # ── Paint semi-transparent background ──────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

    # ── Updates ────────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        # FPS – MangoHud integration (read from /tmp/mango_fps if available)
        fps = self._read_mangohud_fps()
        self.fps_lbl.setText(f"FPS:  {fps if fps else '—'}")

        # Ping (updated by worker thread)
        if self._ping_ms < 0:
            self.ping_lbl.setText("Ping: timeout")
            self.ping_lbl.setStyleSheet("color: #ef5350; background: transparent;")
        else:
            color = "#4caf50" if self._ping_ms < 80 else "#f59e0b" if self._ping_ms < 200 else "#ef5350"
            self.ping_lbl.setText(f"Ping: {self._ping_ms}ms")
            self.ping_lbl.setStyleSheet(f"color: {color}; background: transparent;")

        # RAM
        ram = _get_roblox_ram_mb()
        self.ram_lbl.setText(f"RAM:  {ram}MB" if ram else "RAM:  —")

        # Session
        app_name, remaining = _get_session_info()
        if remaining:
            color = "#4caf50" if "h" in remaining else "#f59e0b"
            self.session_lbl.setText(f"⏱ {remaining}")
            self.session_lbl.setStyleSheet(f"color: {color}; background: transparent;")
        else:
            self.session_lbl.setText("Sesja: —")
            self.session_lbl.setStyleSheet("color: #888888; background: transparent;")

    def _on_ping(self, ms: int) -> None:
        self._ping_ms = ms

    @staticmethod
    def _read_mangohud_fps() -> Optional[int]:
        """Try to read FPS from MangoHud output file."""
        try:
            p = Path("/tmp/MangoHud.log")
            if p.exists():
                lines = p.read_text().splitlines()
                for line in reversed(lines[-5:]):
                    if "fps" in line.lower():
                        parts = line.split()
                        for part in parts:
                            if part.isdigit():
                                return int(part)
        except OSError:
            pass
        return None

    def toggle_visibility(self) -> None:
        self._visible = not self._visible
        self.setVisible(self._visible)

    def closeEvent(self, event) -> None:
        self._ping_worker.stop()
        self._ping_worker.wait(2000)
        super().closeEvent(event)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("RobloxOS Stats Overlay")

    overlay = StatsOverlay()
    overlay.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
