#!/usr/bin/env python3
"""
RobloxOS Launcher
Fullscreen tile-based launcher that replaces the desktop.
"""

import subprocess
import sys
import os
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QGridLayout,
    QPushButton, QLabel, QVBoxLayout, QHBoxLayout, QFrame
)
from PyQt6.QtCore import Qt, QSize, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QPixmap, QPainter, QBrush


# ── App launch commands ────────────────────────────────────────────────────────

APPS = {
    "roblox": {
        "label": "Roblox",
        "icon": "🎮",
        "cmd": ["sober"],                         # Sober wrapper
        "color_bg": "#e53935",
        "color_hover": "#ef5350",
        "color_press": "#b71c1c",
    },
    "discord": {
        "label": "Discord",
        "icon": "🎧",
        "cmd": ["python3", "/opt/robloxos/discord_launcher.py"],  # smart launcher
        "color_bg": "#5865f2",
        "color_hover": "#7289da",
        "color_press": "#3c45a5",
    },
    "browser": {
        "label": "Przeglądarka",
        "icon": "🌐",
        "cmd": [
            "chromium-browser",
            # ── Bezpieczeństwo ─────────────────────────────────────────
            "--kiosk",                          # fullscreen, brak paska adresu
            "--no-first-run",                   # pomija ekran powitalny Chrome
            "--no-default-browser-check",       # bez pytania o ustawienie domyślnej
            "--disable-translate",              # brak paska tłumaczenia
            "--disable-infobars",               # brak żadnych info-pasków u góry
            "--disable-suggestions-service",    # brak autouzupełniania adresów
            "--disable-save-password-bubble",   # brak pytania o zapis hasła
            "--disable-sync",                   # brak synchronizacji konta Google
            "--disable-background-networking",  # brak ruchu sieciowego w tle
            "--disable-component-update",       # komponenty nie aktualizują się same
            "--disable-features=Translate",
            # ── Extension ──────────────────────────────────────────────
            # Ładujemy TYLKO naszą extension; każda inna jest zablokowana
            "--load-extension=/home/robloxuser/browser",
            "--disable-extensions-except=/home/robloxuser/browser",
            # ── Profil ─────────────────────────────────────────────────
            # Osobny profil żeby nie kolidować z ewentualnym systemowym Chrome
            "--user-data-dir=/home/robloxuser/.chromium-robloxos",
            # ── Start page ─────────────────────────────────────────────
            "https://www.roblox.com",
        ],
        "color_bg": "#1e88e5",
        "color_hover": "#42a5f5",
        "color_press": "#0d47a1",
    },
}


# ── Tile button ────────────────────────────────────────────────────────────────

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
    QPushButton:hover {{
        background-color: {hover};
    }}
    QPushButton:pressed {{
        background-color: {press};
    }}
"""


class TileButton(QWidget):
    """Single launcher tile: icon label + text label stacked vertically."""

    clicked = pyqtSignal(str)  # emits app key

    def __init__(self, key: str, cfg: dict, parent=None):
        super().__init__(parent)
        self.key = key

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.btn = QPushButton()
        self.btn.setFixedSize(QSize(320, 320))
        self.btn.setStyleSheet(TILE_STYLE.format(
            bg=cfg["color_bg"],
            hover=cfg["color_hover"],
            press=cfg["color_press"],
        ))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(lambda: self.clicked.emit(self.key))

        # Icon inside button
        icon_lbl = QLabel(cfg["icon"])
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 80))
        icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        btn_layout = QVBoxLayout(self.btn)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.addWidget(icon_lbl)

        # App name below button
        name_lbl = QLabel(cfg["label"])
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setFont(QFont("Ubuntu", 20, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color: white; margin-top: 18px;")

        layout.addWidget(self.btn, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name_lbl)


# ── Worker – launches app without blocking UI ──────────────────────────────────

class LaunchWorker(QThread):
    error = pyqtSignal(str)

    def __init__(self, cmd: list[str]):
        super().__init__()
        self.cmd = cmd

    def run(self):
        try:
            subprocess.Popen(
                self.cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            self.error.emit(f"Nie znaleziono: {self.cmd[0]}")


# ── Main window ────────────────────────────────────────────────────────────────

class Launcher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RobloxOS")
        self._workers: list[LaunchWorker] = []
        self._build_ui()
        self._go_fullscreen()

    # -- UI construction -------------------------------------------------------

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet("background-color: #0f0f0f;")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(60, 60, 60, 60)
        outer.setSpacing(0)

        # Header
        header = QLabel("RobloxOS")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setFont(QFont("Ubuntu", 36, QFont.Weight.Bold))
        header.setStyleSheet("color: #ffffff; letter-spacing: 4px; margin-bottom: 8px;")
        outer.addWidget(header)

        subtitle = QLabel("Wybierz aplikację")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setFont(QFont("Ubuntu", 14))
        subtitle.setStyleSheet("color: #888888; margin-bottom: 60px;")
        outer.addWidget(subtitle)

        # Tiles row
        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(60)
        tiles_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for key, cfg in APPS.items():
            tile = TileButton(key, cfg)
            tile.clicked.connect(self._launch)
            tiles_row.addWidget(tile)

        outer.addLayout(tiles_row)
        outer.addStretch()

        # Footer hint
        footer = QLabel("© RobloxOS  |  naciśnij F11 aby opuścić tryb pełnoekranowy")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setFont(QFont("Ubuntu", 10))
        footer.setStyleSheet("color: #333333; margin-top: 40px;")
        outer.addWidget(footer)

    # -- Fullscreen ------------------------------------------------------------

    def _go_fullscreen(self):
        self.showFullScreen()

    def keyPressEvent(self, event):
        # F11 exits fullscreen (debug only – will be removed in production)
        if event.key() == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        # Block Alt+F4, Alt+Tab etc. at Qt level (Openbox handles the rest)
        elif event.modifiers() & Qt.KeyboardModifier.AltModifier:
            event.ignore()
            return
        super().keyPressEvent(event)

    # -- Launch ----------------------------------------------------------------

    def _launch(self, key: str):
        cfg = APPS[key]
        worker = LaunchWorker(cfg["cmd"])
        worker.error.connect(self._on_error)
        self._workers.append(worker)   # keep reference so GC doesn't kill thread
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def _on_error(self, msg: str):
        # In production replace with a styled overlay dialog
        print(f"[launcher] ERROR: {msg}", file=sys.stderr)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    # Hide mouse cursor for console-like feel (optional)
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    app = QApplication(sys.argv)
    app.setApplicationName("RobloxOS Launcher")

    # Dark palette fallback
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0f0f0f"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#ffffff"))
    app.setPalette(palette)

    window = Launcher()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
