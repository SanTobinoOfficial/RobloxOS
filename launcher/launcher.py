#!/usr/bin/env python3
"""RobloxOS Launcher v2.0 – fullscreen tile launcher z VM detection, session timer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import (
    Qt, QSize, QThread, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve,
)
from PyQt6.QtGui import QColor, QFont, QPalette
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QPushButton,
    QVBoxLayout, QWidget, QFrame, QGraphicsOpacityEffect,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
CONFIG_PATH      = Path("/etc/robloxos/config.json")
STATE_PATH       = Path("/var/lib/robloxos/session_times.json")
SESSION_TIMER_PY = Path("/home/robloxuser/launcher/session_timer.py")

# ── VM detection ───────────────────────────────────────────────────────────────

def detect_vm() -> tuple[bool, str]:
    """Return (is_vm, virt_type). Uses systemd-detect-virt + DMI fallback."""
    try:
        result = subprocess.run(
            ["systemd-detect-virt"],
            capture_output=True, text=True, timeout=3,
        )
        virt = result.stdout.strip()
        if virt and virt != "none":
            return True, virt
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # DMI fallback (readable without root)
    dmi_files = [
        "/sys/class/dmi/id/product_name",
        "/sys/class/dmi/id/sys_vendor",
    ]
    vm_keywords = {"virtualbox", "vmware", "qemu", "kvm", "xen", "hyper-v", "bochs"}
    for path in dmi_files:
        try:
            content = Path(path).read_text().lower()
            for kw in vm_keywords:
                if kw in content:
                    return True, kw
        except OSError:
            pass

    return False, "none"


IS_VM, VIRT_TYPE = detect_vm()

# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    """Load /etc/robloxos/config.json with safe defaults."""
    defaults: dict = {
        "time_limits": {"roblox": 120, "discord": 60, "browser": 30},
        "schedule": {"enabled": False},
        "vm_mode": False,
        "whitelist": [],
    }
    try:
        data = json.loads(CONFIG_PATH.read_text())
        defaults.update(data)
    except (OSError, json.JSONDecodeError):
        pass
    return defaults


CONFIG = load_config()

# ── App definitions ────────────────────────────────────────────────────────────

# In VM mode Sober won't work – use dummy echo instead
_sober_cmd = (
    ["echo", "Sober nie działa w VM – uruchom na prawdziwym sprzęcie"]
    if IS_VM
    else ["flatpak", "run", "org.vinegarhq.Sober"]
)

APPS: dict[str, dict] = {
    "roblox": {
        "label": "Roblox",
        "icon": "🎮",
        "cmd": _sober_cmd,
        "color_bg": "#e53935",
        "color_hover": "#ef5350",
        "color_press": "#b71c1c",
        "limit_key": "roblox",
    },
    "discord": {
        "label": "Discord",
        "icon": "🎧",
        "cmd": [sys.executable, "/home/robloxuser/launcher/discord_launcher.py"],
        "color_bg": "#5865f2",
        "color_hover": "#7289da",
        "color_press": "#3c45a5",
        "limit_key": "discord",
    },
    "browser": {
        "label": "Przeglądarka",
        "icon": "🌐",
        "cmd": [
            "chromium-browser",
            "--kiosk",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-translate",
            "--disable-infobars",
            "--disable-suggestions-service",
            "--disable-save-password-bubble",
            "--disable-sync",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-features=Translate",
            "--load-extension=/home/robloxuser/browser",
            "--disable-extensions-except=/home/robloxuser/browser",
            "--user-data-dir=/home/robloxuser/.chromium-robloxos",
            "https://www.roblox.com",
        ],
        "color_bg": "#1e88e5",
        "color_hover": "#42a5f5",
        "color_press": "#0d47a1",
        "limit_key": "browser",
    },
}

# ── Styles ─────────────────────────────────────────────────────────────────────

TILE_STYLE = """
    QPushButton {{
        background-color: {bg};
        border: none;
        border-radius: 24px;
        color: white;
        font-size: 32px;
        font-weight: bold;
        padding: 0;
    }}
    QPushButton:hover   {{ background-color: {hover}; }}
    QPushButton:pressed {{ background-color: {press}; }}
    QPushButton:disabled {{
        background-color: #333333;
        color: #666666;
    }}
"""

# ── Worker thread ──────────────────────────────────────────────────────────────

class LaunchWorker(QThread):
    """Launches a subprocess without blocking the UI."""

    error = pyqtSignal(str)

    def __init__(self, cmd: list[str]) -> None:
        super().__init__()
        self.cmd = cmd

    def run(self) -> None:
        try:
            subprocess.Popen(
                self.cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.error.emit(f"Nie znaleziono: {self.cmd[0]}")
        except Exception as exc:
            self.error.emit(str(exc))


# ── Session timer integration ──────────────────────────────────────────────────

class SessionTimerThread(QThread):
    """Wraps session_timer.py as a background thread."""

    limit_reached = pyqtSignal(str, int)   # (app_key, remaining_seconds)
    time_updated  = pyqtSignal(str, int)   # (app_key, used_seconds)

    def __init__(self) -> None:
        super().__init__()
        self._active_app: Optional[str] = None
        self._running = True

    def set_active_app(self, key: Optional[str]) -> None:
        self._active_app = key

    def run(self) -> None:
        """Poll session_times.json and emit signals as needed."""
        import time

        while self._running:
            try:
                if self._active_app and STATE_PATH.exists():
                    data = json.loads(STATE_PATH.read_text())
                    used = int(data.get(self._active_app, 0))
                    limit = CONFIG["time_limits"].get(self._active_app, 0)
                    self.time_updated.emit(self._active_app, used)
                    if limit > 0 and used >= limit * 60:
                        self.limit_reached.emit(self._active_app, 0)
            except Exception:
                pass
            time.sleep(5)

    def stop(self) -> None:
        self._running = False


# ── VM banner ──────────────────────────────────────────────────────────────────

class VMBanner(QFrame):
    """Yellow banner shown at the top in VM / test mode."""

    def __init__(self, virt_type: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background-color: #f59e0b; border-radius: 8px;"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)

        icon = QLabel("⚙")
        icon.setFont(QFont("Ubuntu", 18))
        icon.setStyleSheet("color: #1a1a1a;")

        text = QLabel(
            f"TRYB TESTOWY  |  Środowisko wirtualne: {virt_type.upper()}  |  "
            "AppArmor: complain  |  Sober niedostępny"
        )
        text.setFont(QFont("Ubuntu", 12, QFont.Weight.Bold))
        text.setStyleSheet("color: #1a1a1a;")

        layout.addWidget(icon)
        layout.addSpacing(8)
        layout.addWidget(text)
        layout.addStretch()


# ── Tile button ────────────────────────────────────────────────────────────────

class TileButton(QWidget):
    """Single launcher tile with icon + label + optional time-remaining ring."""

    clicked = pyqtSignal(str)

    def __init__(self, key: str, cfg: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.key = key
        self._limit_minutes = CONFIG["time_limits"].get(cfg["limit_key"], 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Button
        self.btn = QPushButton()
        self.btn.setFixedSize(QSize(300, 300))
        self.btn.setStyleSheet(TILE_STYLE.format(
            bg=cfg["color_bg"],
            hover=cfg["color_hover"],
            press=cfg["color_press"],
        ))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(lambda: self.clicked.emit(self.key))

        icon_lbl = QLabel(cfg["icon"])
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setFont(QFont("Noto Color Emoji", 72))
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        btn_layout = QVBoxLayout(self.btn)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(icon_lbl)

        # App name
        name_lbl = QLabel(cfg["label"])
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setFont(QFont("Ubuntu", 18, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color: white; margin-top: 16px;")

        # Time remaining label
        self.time_lbl = QLabel("")
        self.time_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_lbl.setFont(QFont("Ubuntu", 11))
        self.time_lbl.setStyleSheet("color: #888888;")

        layout.addWidget(self.btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_lbl)
        layout.addWidget(self.time_lbl)

    def update_time(self, used_seconds: int) -> None:
        """Update the time remaining label below the tile."""
        if self._limit_minutes <= 0:
            self.time_lbl.setText("")
            return
        limit_sec = self._limit_minutes * 60
        remaining = max(0, limit_sec - used_seconds)
        h, m = divmod(remaining // 60, 60)
        if h:
            self.time_lbl.setText(f"Pozostało: {h}h {m}min")
        else:
            self.time_lbl.setText(f"Pozostało: {m} min")

        # Disable tile if time is up
        exhausted = remaining == 0
        self.btn.setEnabled(not exhausted)
        if exhausted:
            self.time_lbl.setText("Limit wyczerpany")
            self.time_lbl.setStyleSheet("color: #e53935;")


# ── Session expired overlay ────────────────────────────────────────────────────

class SessionExpiredOverlay(QWidget):
    """Fullscreen overlay shown when time limit is reached."""

    dismissed = pyqtSignal()

    def __init__(self, app_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._countdown = 60
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setStyleSheet("background-color: rgba(0,0,0,220);")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        icon = QLabel("⏰")
        icon.setFont(QFont("Noto Color Emoji", 80))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("Czas minął!")
        title.setFont(QFont("Ubuntu", 42, QFont.Weight.Bold))
        title.setStyleSheet("color: #e53935;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.subtitle = QLabel(
            f"Dzienny limit dla <b>{app_name}</b> dobiegł końca.<br>"
            "Aplikacja zostanie zamknięta za:"
        )
        self.subtitle.setFont(QFont("Ubuntu", 16))
        self.subtitle.setStyleSheet("color: #cccccc;")
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setTextFormat(Qt.TextFormat.RichText)

        self.countdown_lbl = QLabel("60")
        self.countdown_lbl.setFont(QFont("Ubuntu", 80, QFont.Weight.Bold))
        self.countdown_lbl.setStyleSheet("color: #f59e0b;")
        self.countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info = QLabel("Limity resetują się o północy. Porozmawiaj z rodzicem. 😊")
        info.setFont(QFont("Ubuntu", 13))
        info.setStyleSheet("color: #666666;")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for w in (icon, title, self.subtitle, self.countdown_lbl, info):
            layout.addWidget(w)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _tick(self) -> None:
        self._countdown -= 1
        self.countdown_lbl.setText(str(self._countdown))
        if self._countdown <= 0:
            self._timer.stop()
            self.dismissed.emit()


# ── Error dialog ───────────────────────────────────────────────────────────────

class ErrorOverlay(QWidget):
    """Small non-blocking error notification."""

    def __init__(self, message: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #e53935; border-radius: 12px;"
        )
        self.setFixedSize(400, 80)

        layout = QHBoxLayout(self)
        icon = QLabel("⚠")
        icon.setFont(QFont("Ubuntu", 20))
        icon.setStyleSheet("color: #e53935;")
        msg = QLabel(message)
        msg.setFont(QFont("Ubuntu", 12))
        msg.setStyleSheet("color: #ffffff; border: none;")
        msg.setWordWrap(True)
        layout.addWidget(icon)
        layout.addWidget(msg)

        QTimer.singleShot(4000, self.hide)


# ── Main window ────────────────────────────────────────────────────────────────

class Launcher(QMainWindow):
    """Fullscreen launcher – main application window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RobloxOS")
        self._workers: list[LaunchWorker] = []
        self._tiles: dict[str, TileButton] = {}
        self._overlay: Optional[SessionExpiredOverlay] = None
        self._active_app: Optional[str] = None

        self._build_ui()
        self._start_session_timer()
        self.showFullScreen()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        root.setStyleSheet("background-color: #0f0f0f;")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(60, 40, 60, 40)
        outer.setSpacing(0)

        # VM banner (tylko gdy VM)
        if IS_VM:
            outer.addWidget(VMBanner(VIRT_TYPE))
            outer.addSpacing(20)

        # Header
        header = QLabel("RobloxOS")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFont(QFont("Ubuntu", 36, QFont.Weight.Bold))
        header.setStyleSheet("color: #ffffff; letter-spacing: 4px;")
        outer.addWidget(header)

        subtitle_text = "Tryb testowy – VirtualBox" if IS_VM else "Wybierz aplikację"
        subtitle = QLabel(subtitle_text)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFont(QFont("Ubuntu", 14))
        subtitle.setStyleSheet(
            "color: #f59e0b; margin-bottom: 40px;" if IS_VM
            else "color: #888888; margin-bottom: 40px;"
        )
        outer.addWidget(subtitle)

        # Tiles row
        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(60)
        tiles_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for key, cfg in APPS.items():
            tile = TileButton(key, cfg)
            tile.clicked.connect(self._launch)
            tiles_row.addWidget(tile)
            self._tiles[key] = tile

        outer.addLayout(tiles_row)
        outer.addStretch()

        # Footer
        footer_text = (
            f"VirtualBox · {VIRT_TYPE} · AppArmor: complain  |  F11 = okno"
            if IS_VM
            else "© RobloxOS v2.0"
        )
        footer = QLabel(footer_text)
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setFont(QFont("Ubuntu", 10))
        footer.setStyleSheet("color: #2a2a2a;" if not IS_VM else "color: #f59e0b;")
        outer.addWidget(footer)

    # ── Session timer ──────────────────────────────────────────────────────────

    def _start_session_timer(self) -> None:
        self._session_thread = SessionTimerThread()
        self._session_thread.time_updated.connect(self._on_time_updated)
        self._session_thread.limit_reached.connect(self._on_limit_reached)
        self._session_thread.start()

    def _on_time_updated(self, app_key: str, used_seconds: int) -> None:
        if app_key in self._tiles:
            self._tiles[app_key].update_time(used_seconds)

    def _on_limit_reached(self, app_key: str, _remaining: int) -> None:
        """Show fullscreen overlay and kill the running app after countdown."""
        if self._overlay is not None:
            return  # already showing

        app_name = APPS.get(app_key, {}).get("label", app_key)
        self._overlay = SessionExpiredOverlay(app_name, self.centralWidget())
        self._overlay.setGeometry(self.centralWidget().rect())
        self._overlay.show()
        self._overlay.dismissed.connect(lambda: self._dismiss_overlay(app_key))

    def _dismiss_overlay(self, app_key: str) -> None:
        if self._overlay:
            self._overlay.deleteLater()
            self._overlay = None
        # Kill the app process tree
        self._kill_app(app_key)
        self._active_app = None
        self._session_thread.set_active_app(None)

    def _kill_app(self, app_key: str) -> None:
        """Kill all processes belonging to the app (best-effort)."""
        import signal as sig
        process_names = {
            "roblox":  ["sober", "RobloxPlayer"],
            "discord": ["discord"],
            "browser": ["chromium", "chromium-browser"],
        }
        for name in process_names.get(app_key, []):
            try:
                subprocess.run(
                    ["pkill", "-SIGTERM", "-f", name],
                    capture_output=True, timeout=3,
                )
            except Exception:
                pass

    # ── Keyboard ───────────────────────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        if IS_VM and event.key() == Qt.Key.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
            return
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            event.ignore()
            return
        super().keyPressEvent(event)

    # ── Launch ─────────────────────────────────────────────────────────────────

    def _launch(self, key: str) -> None:
        cfg = APPS[key]

        # Check schedule
        if not self._check_schedule():
            self._show_error("Dostęp zablokowany – poza godzinami dostępu.")
            return

        # Check time limit
        tile = self._tiles.get(key)
        if tile and not tile.btn.isEnabled():
            self._show_error(f"Dzienny limit dla {cfg['label']} wyczerpany.")
            return

        self._active_app = key
        self._session_thread.set_active_app(key)

        worker = LaunchWorker(cfg["cmd"])
        worker.error.connect(self._show_error)
        self._workers.append(worker)
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        worker.start()

    def _check_schedule(self) -> bool:
        """Return False if access is blocked by schedule."""
        from datetime import datetime
        sched = CONFIG.get("schedule", {})
        if not sched.get("enabled", False):
            return True
        now = datetime.now()
        day = now.weekday()
        if day not in sched.get("days", list(range(7))):
            return False
        start = datetime.strptime(sched.get("start", "00:00"), "%H:%M").time()
        end   = datetime.strptime(sched.get("end",   "23:59"), "%H:%M").time()
        return start <= now.time() <= end

    def _show_error(self, message: str) -> None:
        err = ErrorOverlay(message, self.centralWidget())
        # Position bottom-right
        cw = self.centralWidget()
        err.move(cw.width() - err.width() - 20, cw.height() - err.height() - 20)
        err.show()

    def closeEvent(self, event) -> None:
        if hasattr(self, "_session_thread"):
            self._session_thread.stop()
            self._session_thread.wait(2000)
        super().closeEvent(event)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    # Wayland/X11 backend selection
    if IS_VM:
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    else:
        # Try Wayland first, fall back to X11
        os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")

    app = QApplication(sys.argv)
    app.setApplicationName("RobloxOS Launcher")
    app.setApplicationVersion("2.0")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0f0f0f"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
    app.setPalette(palette)

    window = Launcher()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
