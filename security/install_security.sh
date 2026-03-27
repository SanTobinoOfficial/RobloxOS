#!/usr/bin/env bash
# /opt/robloxos/install_security.sh
# RobloxOS – instalator warstwy bezpieczeństwa
#
# Uruchom jako root na zainstalowanym Ubuntu 22.04:
#   sudo bash install_security.sh
#
# Skrypt jest IDEMPOTENTNY – bezpieczne wielokrotne wywołanie.
# Każdy krok sprawdza stan przed wykonaniem zmiany.

set -euo pipefail
IFS=$'\n\t'

# ── Kolory i helper funkcje ───────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  [OK]${NC} $*"; }
info() { echo -e "${CYAN}  [..] $*${NC}"; }
warn() { echo -e "${YELLOW}  [!!] $*${NC}"; }
fail() { echo -e "${RED}  [BŁĄD] $*${NC}" >&2; exit 1; }

step() { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}"; }

# ── Stałe ────────────────────────────────────────────────────────────────────
ROBLOX_USER="robloxuser"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OPT_DIR="/opt/robloxos"
CHECKLIST=()   # wypełniane przez każdy krok

# ── Wymagania wstępne ─────────────────────────────────────────────────────────
step "Sprawdzam wymagania wstępne"

[[ $EUID -eq 0 ]] || fail "Ten skrypt musi być uruchomiony jako root (sudo)."

id "$ROBLOX_USER" &>/dev/null || \
    fail "Użytkownik '$ROBLOX_USER' nie istnieje. Utwórz go najpierw: useradd -m $ROBLOX_USER"

for cmd in apparmor_parser aa-enforce visudo systemctl python3; do
    command -v "$cmd" &>/dev/null || fail "Brakuje polecenia: $cmd"
done

ok "Wszystkie wymagania spełnione."


# ══════════════════════════════════════════════════════════════════════════════
step "1/7 – sudoers"
# ══════════════════════════════════════════════════════════════════════════════

SUDOERS_SRC="$SCRIPT_DIR/sudoers.d/robloxuser"
SUDOERS_DST="/etc/sudoers.d/robloxuser"

info "Walidacja składni sudoers..."
visudo -cf "$SUDOERS_SRC" || fail "Błąd składni w $SUDOERS_SRC"

info "Kopiowanie $SUDOERS_DST..."
cp "$SUDOERS_SRC" "$SUDOERS_DST"
chmod 440 "$SUDOERS_DST"
chown root:root "$SUDOERS_DST"

ok "sudoers zainstalowany."
CHECKLIST+=("sudoers: $SUDOERS_DST [chmod 440]")


# ══════════════════════════════════════════════════════════════════════════════
step "2/7 – AppArmor profile: launcher"
# ══════════════════════════════════════════════════════════════════════════════

LAUNCHER_PROF_SRC="$SCRIPT_DIR/apparmor.d/robloxos.launcher"
LAUNCHER_PROF_DST="/etc/apparmor.d/robloxos.launcher"

info "Ładuję profil AppArmor dla launchera..."
cp "$LAUNCHER_PROF_SRC" "$LAUNCHER_PROF_DST"
apparmor_parser -r "$LAUNCHER_PROF_DST" || fail "Błąd parsowania profilu launchera."
aa-enforce "$LAUNCHER_PROF_DST"

ok "AppArmor launcher: enforce."
CHECKLIST+=("AppArmor launcher: enforce ($LAUNCHER_PROF_DST)")


# ══════════════════════════════════════════════════════════════════════════════
step "3/7 – AppArmor profile: Chromium"
# ══════════════════════════════════════════════════════════════════════════════

CHROMIUM_PROF_SRC="$SCRIPT_DIR/apparmor.d/robloxos.chromium"
CHROMIUM_PROF_DST="/etc/apparmor.d/robloxos.chromium"

info "Ładuję profil AppArmor dla Chromium..."
cp "$CHROMIUM_PROF_SRC" "$CHROMIUM_PROF_DST"
apparmor_parser -r "$CHROMIUM_PROF_DST" || fail "Błąd parsowania profilu Chromium."
aa-enforce "$CHROMIUM_PROF_DST"

ok "AppArmor Chromium: enforce."
CHECKLIST+=("AppArmor Chromium: enforce ($CHROMIUM_PROF_DST)")


# ══════════════════════════════════════════════════════════════════════════════
step "4/7 – profile.d (blokada shella)"
# ══════════════════════════════════════════════════════════════════════════════

PROFILED_SRC="$SCRIPT_DIR/profile.d/robloxos.sh"
PROFILED_DST="/etc/profile.d/robloxos.sh"

info "Instaluję /etc/profile.d/robloxos.sh..."
cp "$PROFILED_SRC" "$PROFILED_DST"
chmod 644 "$PROFILED_DST"
chown root:root "$PROFILED_DST"

# Zmień shell użytkownika na nologin (główna blokada)
CURRENT_SHELL=$(getent passwd "$ROBLOX_USER" | cut -d: -f7)
if [[ "$CURRENT_SHELL" != "/usr/sbin/nologin" ]]; then
    info "Zmieniam shell $ROBLOX_USER: $CURRENT_SHELL → /usr/sbin/nologin"
    usermod -s /usr/sbin/nologin "$ROBLOX_USER"
    ok "Shell zmieniony na nologin."
else
    ok "Shell już ustawiony na nologin – pomijam."
fi

CHECKLIST+=("Shell robloxuser: /usr/sbin/nologin")
CHECKLIST+=("profile.d: $PROFILED_DST")


# ══════════════════════════════════════════════════════════════════════════════
step "5/7 – polkit rules"
# ══════════════════════════════════════════════════════════════════════════════

POLKIT_SRC="$SCRIPT_DIR/polkit/10-robloxos.rules"
POLKIT_DST="/etc/polkit-1/rules.d/10-robloxos.rules"

info "Instaluję polkit rules..."
mkdir -p /etc/polkit-1/rules.d
cp "$POLKIT_SRC" "$POLKIT_DST"
chmod 644 "$POLKIT_DST"
chown root:root "$POLKIT_DST"

# Przeładuj polkit jeśli działa
if systemctl is-active --quiet polkit; then
    systemctl reload-or-restart polkit
    ok "polkit przeładowany."
else
    warn "polkit nie jest uruchomiony – reguły zadziałają po starcie."
fi

CHECKLIST+=("polkit: $POLKIT_DST")


# ══════════════════════════════════════════════════════════════════════════════
step "6/7 – usuwanie niepotrzebnych grup"
# ══════════════════════════════════════════════════════════════════════════════

DANGEROUS_GROUPS=(sudo adm plugdev cdrom floppy audio video lpadmin sambashare)

for grp in "${DANGEROUS_GROUPS[@]}"; do
    if id -nG "$ROBLOX_USER" | grep -qw "$grp"; then
        info "Usuwam $ROBLOX_USER z grupy: $grp"
        gpasswd -d "$ROBLOX_USER" "$grp" 2>/dev/null || true
    fi
done

# Zostaw w grupie 'audio' i 'video' jeśli gra wymaga (Roblox/Discord)
# Odkomentuj poniższe jeśli Roblox nie ma dźwięku:
# usermod -aG audio,video "$ROBLOX_USER"

ok "Grupy oczyszczone."
CHECKLIST+=("Grupy: usunięto ${DANGEROUS_GROUPS[*]}")


# ══════════════════════════════════════════════════════════════════════════════
step "7/7 – Watchdog (instalacja + systemd)"
# ══════════════════════════════════════════════════════════════════════════════

# Katalog docelowy
mkdir -p "$OPT_DIR"

info "Kopię watchdog.py do $OPT_DIR..."
cp "$SCRIPT_DIR/watchdog/watchdog.py" "$OPT_DIR/watchdog.py"
chmod 750 "$OPT_DIR/watchdog.py"
chown root:root "$OPT_DIR/watchdog.py"

# Zainstaluj psutil jeśli brak
if ! python3 -c "import psutil" &>/dev/null; then
    info "Instaluję psutil..."
    pip3 install --quiet psutil
fi

# Skopiuj unit
UNIT_SRC="$SCRIPT_DIR/watchdog/watchdog.service"
UNIT_DST="/etc/systemd/system/robloxos-watchdog.service"

cp "$UNIT_SRC" "$UNIT_DST"
chmod 644 "$UNIT_DST"
chown root:root "$UNIT_DST"

systemctl daemon-reload

if systemctl is-enabled --quiet robloxos-watchdog 2>/dev/null; then
    ok "Watchdog już włączony – restartuję..."
    systemctl restart robloxos-watchdog
else
    info "Włączam i startuję robloxos-watchdog..."
    systemctl enable --now robloxos-watchdog
fi

# Sprawdź czy watchdog działa
sleep 2
if systemctl is-active --quiet robloxos-watchdog; then
    ok "Watchdog działa."
else
    warn "Watchdog nie uruchomił się! Sprawdź: journalctl -u robloxos-watchdog"
fi

CHECKLIST+=("Watchdog: $OPT_DIR/watchdog.py")
CHECKLIST+=("Watchdog service: $UNIT_DST [enabled + active]")


# ══════════════════════════════════════════════════════════════════════════════
step "Checklista wyników"
# ══════════════════════════════════════════════════════════════════════════════

echo ""
echo -e "${BOLD}Zainstalowane komponenty:${NC}"
for item in "${CHECKLIST[@]}"; do
    echo -e "  ${GREEN}✓${NC} $item"
done

echo ""
echo -e "${BOLD}Weryfikacja ręczna:${NC}"
cat <<'VERIFY'
  # 1. sudo (powinno odmówić):
  su - robloxuser -s /bin/bash -c "sudo id"

  # 2. AppArmor status:
  aa-status | grep robloxos

  # 3. Watchdog logi:
  journalctl -u robloxos-watchdog --since "5 minutes ago"
  tail -20 /var/log/robloxos-watchdog.log

  # 4. Grupy użytkownika:
  id robloxuser

  # 5. Shell:
  getent passwd robloxuser | cut -d: -f7

  # 6. polkit (powinno zwrócić "not authorized"):
  su - robloxuser -s /bin/bash -c "pkexec --user root id" 2>&1 || true
VERIFY

echo ""
echo -e "${BOLD}${GREEN}Instalacja zakończona pomyślnie.${NC}"
echo -e "${YELLOW}Zalecany restart systemu: sudo reboot${NC}"
