#!/usr/bin/env python3
"""
RobloxOS OTA Updater
Sprawdza GitHub repo co noc i aktualizuje zmienione pliki.
Uruchamiany przez systemd timer (ota.timer).

Pliki które może aktualizować (bez potwierdzenia admina):
  - launcher/launcher.py
  - launcher/discord_launcher.py
  - launcher/session_timer.py
  - browser/rules.json
  - browser/background.js
  - browser/blocked.html
  - overlay/stats_overlay.py

Pliki wymagające potwierdzenia admina (NIGDY nie aktualizowane automatycznie):
  - security/*
  - iso/*
  - build.sh
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Config ─────────────────────────────────────────────────────────────────────
CONFIG_FILE  = Path("/etc/robloxos/config.json")
LOG_FILE     = Path("/var/log/robloxos-ota.log")
INSTALL_BASE = Path("/home/robloxuser")
BACKUP_DIR   = Path("/var/lib/robloxos/ota-backups")
STATE_FILE   = Path("/var/lib/robloxos/ota-state.json")

# Pliki dozwolone do auto-aktualizacji (ścieżki względem root repozytorium)
AUTO_UPDATE_PATHS = {
    "launcher/launcher.py":          INSTALL_BASE / "launcher/launcher.py",
    "launcher/discord_launcher.py":  INSTALL_BASE / "launcher/discord_launcher.py",
    "launcher/session_timer.py":     INSTALL_BASE / "launcher/session_timer.py",
    "browser/rules.json":            INSTALL_BASE / "browser/rules.json",
    "browser/background.js":         INSTALL_BASE / "browser/background.js",
    "browser/blocked.html":          INSTALL_BASE / "browser/blocked.html",
    "overlay/stats_overlay.py":      Path("/opt/robloxos/overlay/stats_overlay.py"),
}

ROBLOX_USER_UID = 1000  # uid robloxusera

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("ota-updater")

# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"last_check": "", "last_commit": "", "updates_applied": 0}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ── SHA256 helpers ─────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── GitHub API ─────────────────────────────────────────────────────────────────

class GitHubClient:
    """Minimal GitHub API client using only stdlib."""

    def __init__(self, repo_url: str) -> None:
        # repo_url: https://github.com/user/repo  OR  user/repo
        repo_url = repo_url.rstrip("/")
        if repo_url.startswith("https://github.com/"):
            self.repo = repo_url.replace("https://github.com/", "")
        else:
            self.repo = repo_url
        self.api_base = f"https://api.github.com/repos/{self.repo}"
        self.raw_base = f"https://raw.githubusercontent.com/{self.repo}"

    def _get(self, url: str, timeout: int = 15) -> dict | list:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "RobloxOS-OTA/2.0",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())

    def get_latest_commit(self, branch: str = "main") -> str:
        """Return SHA of latest commit on branch."""
        data = self._get(f"{self.api_base}/commits/{branch}")
        return data["sha"]

    def get_file_sha(self, path: str, branch: str = "main") -> Optional[str]:
        """Return GitHub blob SHA for a file (different from content SHA256)."""
        try:
            data = self._get(f"{self.api_base}/contents/{path}?ref={branch}")
            return data.get("sha")
        except Exception:
            return None

    def download_file(self, path: str, branch: str = "main") -> bytes:
        """Download raw file content."""
        url = f"{self.raw_base}/{branch}/{path}"
        req = urllib.request.Request(url, headers={"User-Agent": "RobloxOS-OTA/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()


# ── Backup ─────────────────────────────────────────────────────────────────────

def backup_file(local_path: Path, timestamp: str) -> None:
    """Create a timestamped backup of a file before overwriting."""
    if not local_path.exists():
        return
    backup_path = BACKUP_DIR / timestamp / local_path.name
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_path, backup_path)
    log.debug(f"Backup: {local_path} → {backup_path}")


# ── Launcher restart ───────────────────────────────────────────────────────────

def restart_launcher() -> None:
    """Kill launcher process – openbox autostart loop restarts it."""
    try:
        subprocess.run(
            ["pkill", "-SIGTERM", "-f", "launcher.py"],
            timeout=5, capture_output=True,
        )
        log.info("Launcher zrestartowany po aktualizacji.")
    except Exception as exc:
        log.warning(f"Nie można zrestartować launchera: {exc}")


# ── Main update logic ──────────────────────────────────────────────────────────

class OTAUpdater:

    def __init__(self) -> None:
        self.cfg   = load_config()
        self.state = load_state()

    def run(self) -> None:
        ota_cfg = self.cfg.get("ota", {})
        if not ota_cfg.get("enabled", False):
            log.info("OTA wyłączone w config.json (ota.enabled=false) – pomijam.")
            return

        repo_url = ota_cfg.get("repo_url", "").strip()
        if not repo_url:
            log.error("Brak repo_url w config.json → nie można sprawdzić aktualizacji.")
            return

        log.info(f"OTA check: repo={repo_url}")
        self.state["last_check"] = datetime.now().isoformat()

        try:
            client = GitHubClient(repo_url)
            latest_commit = client.get_latest_commit()
        except Exception as exc:
            log.error(f"Błąd połączenia z GitHub: {exc}")
            save_state(self.state)
            return

        if latest_commit == self.state.get("last_commit"):
            log.info(f"Brak nowych commitów (HEAD={latest_commit[:8]}) – nic do zrobienia.")
            save_state(self.state)
            return

        log.info(f"Nowy commit: {latest_commit[:8]} (poprzedni: {self.state.get('last_commit','—')[:8]})")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        updated: list[str] = []
        errors:  list[str] = []
        launcher_changed = False

        for repo_path, local_path in AUTO_UPDATE_PATHS.items():
            try:
                remote_content = client.download_file(repo_path)
                remote_sha     = sha256_bytes(remote_content)
                local_sha      = sha256_file(local_path)

                if remote_sha == local_sha:
                    log.debug(f"Bez zmian: {repo_path}")
                    continue

                log.info(f"Aktualizuję: {repo_path}")
                backup_file(local_path, timestamp)

                # Atomic write via temp file
                local_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=local_path.parent, delete=False, suffix=".tmp"
                ) as tmp:
                    tmp.write(remote_content)
                    tmp_path = Path(tmp.name)

                # Preserve permissions
                if local_path.exists():
                    mode = local_path.stat().st_mode
                    os.chmod(tmp_path, mode)

                tmp_path.rename(local_path)

                # Fix ownership
                os.chown(local_path, ROBLOX_USER_UID, ROBLOX_USER_UID)

                updated.append(repo_path)
                if "launcher" in repo_path:
                    launcher_changed = True

            except Exception as exc:
                log.error(f"Błąd aktualizacji {repo_path}: {exc}")
                errors.append(f"{repo_path}: {exc}")

        # Commit state
        self.state["last_commit"] = latest_commit
        self.state["updates_applied"] = self.state.get("updates_applied", 0) + len(updated)
        save_state(self.state)

        # Summary
        if updated:
            log.info(f"Zaktualizowano {len(updated)} plik(ów): {', '.join(updated)}")
            if launcher_changed:
                restart_launcher()
        else:
            log.info("Żadne pliki nie wymagały aktualizacji.")

        if errors:
            log.warning(f"Błędy podczas aktualizacji: {errors}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="RobloxOS OTA Updater")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run",    help="Sprawdź i zastosuj aktualizacje")
    sub.add_parser("status", help="Pokaż status OTA")
    args = parser.parse_args()

    if args.cmd == "run" or args.cmd is None:
        OTAUpdater().run()
    elif args.cmd == "status":
        state = load_state()
        print(f"Ostatnie sprawdzenie: {state.get('last_check', '—')}")
        print(f"Ostatni commit:       {state.get('last_commit', '—')[:12]}")
        print(f"Łącznie aktualizacji: {state.get('updates_applied', 0)}")
