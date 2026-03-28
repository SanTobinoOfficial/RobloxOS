#!/usr/bin/env python3
"""
RobloxOS Admin Panel v2.0
PyQt6 GUI dla administratora (rodzica). Wymaga uruchomienia jako root.

Uruchomienie:
    sudo admin-panel
    sudo python3 /opt/robloxos/admin/admin_panel.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox,
    QFrame, QGroupBox, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSlider, QSpinBox,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

# ── Paths ──────────────────────────────────────────────────────────────────────
CONFIG_FILE = Path("/etc/robloxos/config.json")
STATE_FILE  = Path("/var/lib/robloxos/session_times.json")
LOG_FILES   = {
    "Watchdog":   Path("/var/log/robloxos-watchdog.log"),
    "OTA":        Path("/var/log/robloxos-ota.log"),
    "Sesja":      Path("/var/log/robloxos-session.log"),
    "Setup":      Path("/var/log/robloxos-setup.log"),
}

# ── Style ──────────────────────────────────────────────────────────────────────
DARK_STYLE = """
QMainWindow, QDialog, QWidget {
    background-color: #0f0f0f; color: #e0e0e0;
    font-family: Ubuntu, "Segoe UI", sans-serif; font-size: 13px;
}
QTabWidget::pane { border: 1px solid #2a2a2a; border-radius: 8px; }
QTabBar::tab {
    background: #1a1a1a; color: #888; padding: 10px 20px;
    border: 1px solid #2a2a2a; border-bottom: none; border-radius: 6px 6px 0 0;
    margin-right: 2px;
}
QTabBar::tab:selected { background: #242424; color: #fff; border-bottom: 1px solid #242424; }
QPushButton {
    background: #1e88e5; color: #fff; border: none;
    border-radius: 8px; padding: 9px 18px; font-weight: 600;
}
QPushButton:hover   { background: #1565c0; }
QPushButton:pressed { background: #0d47a1; }
QPushButton#danger  { background: #e53935; }
QPushButton#danger:hover { background: #b71c1c; }
QPushButton#ghost {
    background: #1e1e1e; color: #e0e0e0;
    border: 1px solid #2a2a2a;
}
QPushButton#ghost:hover { background: #2a2a2a; }
QLineEdit, QSpinBox {
    background: #0a0a0a; border: 1px solid #2a2a2a;
    border-radius: 8px; padding: 8px 12px; color: #e0e0e0;
}
QLineEdit:focus, QSpinBox:focus { border-color: #1e88e5; }
QListWidget {
    background: #0a0a0a; border: 1px solid #2a2a2a;
    border-radius: 8px; color: #e0e0e0;
}
QListWidget::item:selected { background: #1e1e1e; color: #fff; }
QTextEdit {
    background: #060606; border: 1px solid #2a2a2a; border-radius: 8px;
    color: #a0a0a0; font-family: "Ubuntu Mono", monospace; font-size: 12px;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px;
                       border: 1px solid #2a2a2a; background: #0a0a0a; }
QCheckBox::indicator:checked { background: #1e88e5; border-color: #1e88e5; }
QSlider::groove:horizontal { height: 4px; background: #2a2a2a; border-radius: 2px; }
QSlider::handle:horizontal {
    background: #1e88e5; border-radius: 8px;
    width: 16px; height: 16px; margin: -6px 0;
}
QSlider::sub-page:horizontal { background: #1e88e5; border-radius: 2px; }
QGroupBox {
    border: 1px solid #2a2a2a; border-radius: 8px;
    margin-top: 12px; padding-top: 8px; font-weight: 700;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #888; }
QLabel#header { font-size: 20px; font-weight: 700; color: #e53935; }
QLabel#section { font-size: 11px; color: #666; font-weight: 700;
                 text-transform: uppercase; letter-spacing: 2px; }
"""

# ── Config helpers ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


# ── Log tail thread ────────────────────────────────────────────────────────────

class LogTailThread(QThread):
    new_line = pyqtSignal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self._running = True

    def run(self) -> None:
        import time
        try:
            with open(self.path) as f:
                f.seek(0, 2)
                while self._running:
                    line = f.readline()
                    if line:
                        self.new_line.emit(line.rstrip())
                    else:
                        time.sleep(0.5)
        except OSError:
            pass

    def stop(self) -> None:
        self._running = False


# ── Whitelist tab ──────────────────────────────────────────────────────────────

class WhitelistTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl = QLabel("Dozwolone strony internetowe")
        lbl.setObjectName("header")
        layout.addWidget(lbl)

        info = QLabel(
            "Tylko domeny z tej listy są dostępne w przeglądarce.\n"
            "Subdomeny (np. sub.roblox.com) są dozwolone automatycznie."
        )
        info.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(info)

        # Add row
        add_row = QHBoxLayout()
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("np. wikipedia.org")
        self.domain_input.returnPressed.connect(self._add_domain)
        add_btn = QPushButton("+ Dodaj")
        add_btn.setFixedWidth(90)
        add_btn.clicked.connect(self._add_domain)
        add_row.addWidget(self.domain_input)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        # List
        self.list_widget = QListWidget()
        self._reload_list()
        layout.addWidget(self.list_widget)

        # Remove button
        remove_btn = QPushButton("🗑 Usuń zaznaczoną")
        remove_btn.setObjectName("danger")
        remove_btn.clicked.connect(self._remove_domain)
        layout.addWidget(remove_btn)

    def _reload_list(self) -> None:
        self.list_widget.clear()
        for domain in sorted(self.cfg.get("whitelist", [])):
            self.list_widget.addItem(domain)

    def _add_domain(self) -> None:
        domain = self.domain_input.text().strip().lower()
        if not domain:
            return
        wl = self.cfg.setdefault("whitelist", [])
        if domain in wl:
            QMessageBox.information(self, "Info", f"{domain} już na liście.")
            return
        wl.append(domain)
        save_config(self.cfg)
        self._reload_list()
        self.domain_input.clear()

    def _remove_domain(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        domain = item.text()
        protected = {"roblox.com", "discord.com", "youtube.com"}
        if domain in protected:
            QMessageBox.warning(self, "Błąd", f"{domain} jest chronioną domeną.")
            return
        if QMessageBox.question(
            self, "Potwierdź", f"Usunąć {domain}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        self.cfg["whitelist"] = [d for d in self.cfg["whitelist"] if d != domain]
        save_config(self.cfg)
        self._reload_list()


# ── Time limits tab ────────────────────────────────────────────────────────────

class TimeLimitsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.cfg = load_config()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        lbl = QLabel("Dzienny limit gry")
        lbl.setObjectName("header")
        layout.addWidget(lbl)

        self._sliders: dict[str, QSlider] = {}
        self._labels:  dict[str, QLabel]  = {}

        for key, icon, name, color in [
            ("roblox",  "🎮", "Roblox",        "#e53935"),
            ("discord", "🎧", "Discord",        "#5865f2"),
            ("browser", "🌐", "Przeglądarka",   "#1e88e5"),
        ]:
            group = QGroupBox(f"{icon}  {name}")
            g_layout = QHBoxLayout(group)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 480)
            slider.setSingleStep(15)
            slider.setPageStep(30)
            slider.setValue(self.cfg.get("time_limits", {}).get(key, 60))
            slider.setStyleSheet(f"QSlider::sub-page:horizontal {{ background: {color}; }}")

            val_lbl = QLabel()
            val_lbl.setFixedWidth(72)
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            val_lbl.setFont(QFont("Ubuntu", 13, QFont.Weight.Bold))

            self._sliders[key] = slider
            self._labels[key]  = val_lbl
            self._update_label(key, slider.value())
            slider.valueChanged.connect(lambda v, k=key: self._update_label(k, v))

            g_layout.addWidget(slider)
            g_layout.addWidget(val_lbl)
            layout.addWidget(group)

        # Schedule
        sched_group = QGroupBox("Harmonogram dostępu")
        sched_layout = QVBoxLayout(sched_group)

        self.sched_enabled = QCheckBox("Włącz harmonogram (blokuj poza godzinami)")
        sched = self.cfg.get("schedule", {})
        self.sched_enabled.setChecked(sched.get("enabled", False))
        sched_layout.addWidget(self.sched_enabled)

        time_row = QHBoxLayout()
        time_row.addWidget(QLabel("Od:"))
        self.start_input = QLineEdit(sched.get("start", "15:00"))
        self.start_input.setFixedWidth(80)
        time_row.addWidget(self.start_input)
        time_row.addSpacing(16)
        time_row.addWidget(QLabel("Do:"))
        self.end_input = QLineEdit(sched.get("end", "21:00"))
        self.end_input.setFixedWidth(80)
        time_row.addWidget(self.end_input)
        time_row.addStretch()
        sched_layout.addLayout(time_row)
        layout.addWidget(sched_group)

        save_btn = QPushButton("💾 Zapisz")
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)
        layout.addStretch()

    def _update_label(self, key: str, val: int) -> None:
        if val == 0:
            self._labels[key].setText("∞")
            self._labels[key].setStyleSheet("color: #666;")
        else:
            h, m = divmod(val, 60)
            text = f"{h}h {m:02d}m" if h else f"{m}min"
            self._labels[key].setText(text)
            self._labels[key].setStyleSheet("color: #e0e0e0;")

    def _save(self) -> None:
        self.cfg.setdefault("time_limits", {})
        for key, slider in self._sliders.items():
            self.cfg["time_limits"][key] = slider.value()
        self.cfg["schedule"] = {
            "enabled": self.sched_enabled.isChecked(),
            "days": list(range(7)),
            "start": self.start_input.text().strip(),
            "end":   self.end_input.text().strip(),
        }
        save_config(self.cfg)
        QMessageBox.information(self, "Sukces", "Ustawienia zapisane.")


# ── Logs tab ───────────────────────────────────────────────────────────────────

class LogsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._tail_thread: dict[str, LogTailThread] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        lbl = QLabel("Logi systemowe")
        lbl.setObjectName("header")
        layout.addWidget(lbl)

        # Tabs for each log
        self.log_tabs = QTabWidget()
        for name, path in LOG_FILES.items():
            tab = QWidget()
            tab_layout = QVBoxLayout(tab)
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setObjectName(f"log_{name}")
            try:
                lines = path.read_text().splitlines()[-300:]
                text_edit.setPlainText("\n".join(lines))
                # Scroll to bottom
                cursor = text_edit.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                text_edit.setTextCursor(cursor)
            except OSError:
                text_edit.setPlainText(f"(Plik {path} niedostępny)")

            btn_row = QHBoxLayout()
            refresh_btn = QPushButton("↺ Odśwież")
            refresh_btn.setObjectName("ghost")
            refresh_btn.clicked.connect(
                lambda _, p=path, te=text_edit: self._refresh_log(p, te)
            )
            clear_btn = QPushButton("🗑 Wyczyść widok")
            clear_btn.setObjectName("ghost")
            clear_btn.clicked.connect(text_edit.clear)
            btn_row.addWidget(refresh_btn)
            btn_row.addWidget(clear_btn)
            btn_row.addStretch()

            tab_layout.addWidget(text_edit)
            tab_layout.addLayout(btn_row)
            self.log_tabs.addTab(tab, name)

        layout.addWidget(self.log_tabs)

    def _refresh_log(self, path: Path, text_edit: QTextEdit) -> None:
        try:
            lines = path.read_text().splitlines()[-300:]
            text_edit.setPlainText("\n".join(lines))
        except OSError:
            text_edit.setPlainText(f"(Plik {path} niedostępny)")


# ── System tab ─────────────────────────────────────────────────────────────────

class SystemTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl = QLabel("Zarządzanie systemem")
        lbl.setObjectName("header")
        layout.addWidget(lbl)

        # Services
        svc_group = QGroupBox("Usługi systemd")
        svc_layout = QVBoxLayout(svc_group)
        self.svc_status_lbl = QLabel("Ładowanie...")
        svc_layout.addWidget(self.svc_status_lbl)

        svc_btn_row = QHBoxLayout()
        for svc, label in [
            ("robloxos-watchdog", "↺ Restart watchdog"),
            ("robloxos-webpanel", "↺ Restart panelu web"),
            ("lightdm",           "↺ Restart LightDM"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("ghost")
            btn.clicked.connect(lambda _, s=svc: self._restart_service(s))
            svc_btn_row.addWidget(btn)
        svc_layout.addLayout(svc_btn_row)
        layout.addWidget(svc_group)

        # Session
        sess_group = QGroupBox("Liczniki sesji")
        sess_layout = QVBoxLayout(sess_group)
        self.session_lbl = QLabel()
        self._refresh_session()
        sess_layout.addWidget(self.session_lbl)

        reset_row = QHBoxLayout()
        for app in ("roblox", "discord", "browser", "ALL"):
            btn = QPushButton(f"↺ {app}")
            btn.setObjectName("ghost")
            btn.clicked.connect(
                lambda _, a=app: self._reset_session(None if a == "ALL" else a)
            )
            reset_row.addWidget(btn)
        sess_layout.addLayout(reset_row)
        layout.addWidget(sess_group)

        # System actions
        action_group = QGroupBox("Akcje systemowe")
        action_layout = QHBoxLayout(action_group)

        restart_btn = QPushButton("🔁 Restart systemu")
        restart_btn.setObjectName("danger")
        restart_btn.clicked.connect(self._restart_system)

        shutdown_btn = QPushButton("⏻ Wyłącz system")
        shutdown_btn.setObjectName("danger")
        shutdown_btn.clicked.connect(self._shutdown_system)

        launcher_btn = QPushButton("🔄 Restart launchera")
        launcher_btn.clicked.connect(self._restart_launcher)

        action_layout.addWidget(launcher_btn)
        action_layout.addWidget(restart_btn)
        action_layout.addWidget(shutdown_btn)
        layout.addWidget(action_group)
        layout.addStretch()

        # Auto-refresh service status
        self._refresh_services()
        timer = QTimer(self)
        timer.timeout.connect(self._refresh_services)
        timer.start(10000)

    def _refresh_services(self) -> None:
        lines = []
        for svc in ("robloxos-watchdog", "robloxos-webpanel", "lightdm", "apparmor"):
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=3,
                )
                status = result.stdout.strip()
                icon = "🟢" if status == "active" else "🔴"
                lines.append(f"{icon} {svc}: {status}")
            except Exception:
                lines.append(f"⚪ {svc}: unknown")
        self.svc_status_lbl.setText("\n".join(lines))

    def _refresh_session(self) -> None:
        state = load_state()
        lines = [f"Data: {state.get('date', '—')}"]
        for app in ("roblox", "discord", "browser"):
            used = int(state.get(app, 0))
            h, m = divmod(used // 60, 60)
            lines.append(f"  {app}: {h}h {m:02d}m użyte")
        self.session_lbl.setText("\n".join(lines))

    def _restart_service(self, name: str) -> None:
        try:
            subprocess.run(["systemctl", "restart", name], timeout=10, check=True)
            QMessageBox.information(self, "OK", f"{name} zrestartowany.")
        except subprocess.CalledProcessError as exc:
            QMessageBox.critical(self, "Błąd", str(exc))

    def _reset_session(self, app: str | None) -> None:
        cmd = [sys.executable, "/home/robloxuser/launcher/session_timer.py", "reset"]
        if app:
            cmd.append(app)
        subprocess.run(cmd, timeout=5)
        self._refresh_session()

    def _restart_system(self) -> None:
        if QMessageBox.question(
            self, "Potwierdź", "Zrestartować system?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            subprocess.Popen(["shutdown", "-r", "now"])

    def _shutdown_system(self) -> None:
        if QMessageBox.question(
            self, "Potwierdź", "Wyłączyć system?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            subprocess.Popen(["shutdown", "-h", "now"])

    def _restart_launcher(self) -> None:
        subprocess.run(["pkill", "-f", "launcher.py"], timeout=5, check=False)
        QMessageBox.information(self, "OK", "Launcher zostanie zrestartowany przez autostart.")


# ── Main window ────────────────────────────────────────────────────────────────

class AdminPanel(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RobloxOS Admin Panel v2.0")
        self.setMinimumSize(800, 600)
        self.resize(960, 680)

        tabs = QTabWidget()
        tabs.addTab(WhitelistTab(),  "🌐  Whitelist")
        tabs.addTab(TimeLimitsTab(), "⏱  Limity czasu")
        tabs.addTab(LogsTab(),       "📋  Logi")
        tabs.addTab(SystemTab(),     "⚙  System")
        self.setCentralWidget(tabs)

    def closeEvent(self, event) -> None:
        super().closeEvent(event)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    if os.geteuid() != 0:
        print("BŁĄD: Admin Panel wymaga uprawnień root.")
        print("Uruchom: sudo admin-panel")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setApplicationName("RobloxOS Admin Panel")
    app.setStyleSheet(DARK_STYLE)

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0f0f0f"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e0e0e0"))
    app.setPalette(palette)

    window = AdminPanel()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
