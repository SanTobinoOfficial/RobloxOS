#!/usr/bin/env python3
"""
RobloxOS – Watchdog daemon
Monitoruje procesy uruchomione przez robloxuser i killuje nieautoryzowane.
Uruchamiany jako root przez systemd (watchdog.service).
"""

import os
import signal
import logging
import time
import sys
from logging.handlers import RotatingFileHandler

try:
    import psutil
except ImportError:
    print("BŁĄD: brak modułu psutil. Zainstaluj: pip3 install psutil", file=sys.stderr)
    sys.exit(1)


# ── Konfiguracja ──────────────────────────────────────────────────────────────

WATCHED_USER    = "robloxuser"
CHECK_INTERVAL  = 5          # sekundy między skanami
LOG_FILE        = "/var/log/robloxos-watchdog.log"
LOG_MAX_BYTES   = 5 * 1024 * 1024   # 5 MB
LOG_BACKUP_COUNT = 3

# Procesy które wolno uruchamiać użytkownikowi robloxuser.
# Format: (name_fragment, cmdline_fragment_optional)
# name_fragment: dopasowanie do proc.name() (case-insensitive, partial match)
# cmdline_fragment: dodatkowy filtr na pełne args (None = brak filtra)
ALLOWED_PROCESSES: list[tuple[str, str | None]] = [
    # ── Sesja graficzna ────────────────────────────────────────────────
    ("Xorg",             None),
    ("Xwayland",         None),
    ("openbox",          None),
    ("picom",            None),
    ("unclutter",        None),
    ("dbus-daemon",      None),
    ("dbus-launch",      None),
    ("at-spi",           None),       # accessibility bus (Qt wymaga)
    ("gvfsd",            None),       # GNOME virtual fs (Flatpak)
    ("xdg-",             None),       # xdg-user-dirs, xdg-permission-store itp.
    # ── Launcher RobloxOS ──────────────────────────────────────────────
    ("python3",          "launcher.py"),
    ("python3",          "discord_launcher.py"),
    # ── Aplikacje ──────────────────────────────────────────────────────
    ("sober",            None),       # Roblox wrapper
    ("RobloxPlayer",     None),       # klient Roblox (uruchamiany przez Sober)
    ("wine",             None),       # Sober może używać Wine internaly
    ("wineserver",       None),
    ("discord",          None),       # Flatpak Discord (wiele procesów)
    ("bwrap",            None),       # Flatpak sandbox (bubblewrap)
    ("flatpak",          "run"),      # flatpak run com.discordapp.Discord
    ("chromium",         None),
    ("chromium-browser", None),
    ("chrome",           None),       # chromium może nazwać proces "chrome"
    ("nacl_helper",      None),       # Chromium Native Client
    ("wmctrl",           None),       # pozycjonowanie okna Discorda
    ("xrandr",           None),       # detekcja monitora
    # ── Systemowe (uruchamiane w kontekście usera) ─────────────────────
    ("gnome-keyring",    None),
    ("gpg-agent",        None),
    ("ssh-agent",        None),
    ("pulseaudio",       None),
    ("pipewire",         None),
    ("pipewire-pulse",   None),
    ("wireplumber",      None),
    ("systemd",          None),       # systemd --user
    ("(sd-pam)",         None),
    ("bash",             "autostart"),  # openbox autostart (jednorazowy)
    ("sh",               "autostart"),
]

# Procesy które ZAWSZE ignorujemy (jądro / wątki systemowe)
ALWAYS_IGNORE_NAMES = {"kthreadd", "kworker", "ksoftirqd", "migration",
                       "rcu_", "watchdog/", "irq/"}


# ── Logger ────────────────────────────────────────────────────────────────────

def setup_logger() -> logging.Logger:
    logger = logging.getLogger("robloxos-watchdog")
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Plik (rotating)
    fh = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES,
                              backupCount=LOG_BACKUP_COUNT)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # stdout (widoczne w journalctl)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    return logger


log = setup_logger()


# ── Logika whitelisty ─────────────────────────────────────────────────────────

def is_allowed(proc: psutil.Process) -> bool:
    """Zwraca True jeśli proces jest na whiteliście."""
    try:
        name = proc.name().lower()
        cmdline = " ".join(proc.cmdline()).lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True   # proces zniknął lub nie mamy dostępu – bezpieczny domyślny

    # Zawsze ignoruj wątki jądra
    for ignore in ALWAYS_IGNORE_NAMES:
        if name.startswith(ignore):
            return True

    for name_frag, cmd_frag in ALLOWED_PROCESSES:
        if name_frag.lower() in name:
            if cmd_frag is None:
                return True
            if cmd_frag.lower() in cmdline:
                return True

    return False


def kill_process(proc: psutil.Process) -> None:
    """Zabija nieautoryzowany proces – najpierw SIGTERM, potem SIGKILL."""
    try:
        name    = proc.name()
        pid     = proc.pid
        cmdline = " ".join(proc.cmdline())[:120]   # skróć dla logu

        log.warning(
            f"KILL nieautoryzowany proces: PID={pid} name={name!r} cmd={cmdline!r}"
        )

        proc.send_signal(signal.SIGTERM)
        time.sleep(0.5)

        if proc.is_running():
            proc.send_signal(signal.SIGKILL)
            log.warning(f"SIGKILL wysłany do PID={pid} ({name!r})")

    except psutil.NoSuchProcess:
        pass   # proces sam się skończył – OK
    except psutil.AccessDenied:
        log.error(f"Brak uprawnień do killowania PID={proc.pid} – watchdog musi działać jako root!")
    except Exception as exc:
        log.error(f"Błąd podczas killowania PID={proc.pid}: {exc}")


# ── Pętla główna ──────────────────────────────────────────────────────────────

def get_target_uid() -> int:
    """Pobiera UID użytkownika WATCHED_USER."""
    import pwd
    try:
        return pwd.getpwnam(WATCHED_USER).pw_uid
    except KeyError:
        log.critical(f"Użytkownik {WATCHED_USER!r} nie istnieje na tym systemie!")
        sys.exit(1)


def scan_once(target_uid: int) -> None:
    """Jeden skan: sprawdza wszystkie procesy usera i killuje nieautoryzowane."""
    killed = 0
    for proc in psutil.process_iter(["pid", "name", "uids"]):
        try:
            uids = proc.uids()
            if uids.real != target_uid:
                continue   # nie nasz user
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if not is_allowed(proc):
            kill_process(proc)
            killed += 1

    if killed:
        log.info(f"Skan zakończony: zabito {killed} nieautoryzowanych procesów.")


def main() -> None:
    if os.geteuid() != 0:
        log.critical("Watchdog musi działać jako root (euid=0)!")
        sys.exit(1)

    target_uid = get_target_uid()
    log.info(
        f"RobloxOS Watchdog uruchomiony. "
        f"Monitoruję uid={target_uid} ({WATCHED_USER}), "
        f"interwał={CHECK_INTERVAL}s"
    )

    # Obsługa sygnałów – graceful shutdown
    def _shutdown(signum, frame):
        log.info(f"Otrzymano sygnał {signum} – kończę pracę.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    while True:
        try:
            scan_once(target_uid)
        except Exception as exc:
            log.error(f"Nieoczekiwany błąd w scan_once: {exc}", exc_info=True)
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
