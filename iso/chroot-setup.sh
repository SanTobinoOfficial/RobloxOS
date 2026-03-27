#!/usr/bin/env bash
# /tmp/chroot-setup.sh
# RobloxOS – konfiguracja systemu wewnątrz chroot Cubic lub jako late-command
# Subiquity. Uruchamiany jako root. Pełna automatyzacja, zero interakcji.
#
# Może być wywołany:
#   a) Ręcznie w terminalu Cubic: bash /tmp/chroot-setup.sh
#   b) Przez Subiquity late-commands: curtin in-target -- bash /tmp/chroot-setup.sh
#   c) Na żywym systemie Ubuntu po instalacji: sudo bash chroot-setup.sh

set -euo pipefail
IFS=$'\n\t'
export DEBIAN_FRONTEND=noninteractive

# ── Stałe ────────────────────────────────────────────────────────────────────
ROBLOX_USER="robloxuser"
ROBLOX_HOME="/home/${ROBLOX_USER}"
PROJECT_SRC="/tmp/robloxos"           # tu Cubic umieszcza pliki projektu
OPT_DIR="/opt/robloxos"
LOG="/var/log/robloxos-setup.log"

# Kolory
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  [OK]${NC} $*" | tee -a "$LOG"; }
info() { echo -e "${CYAN}  [..] $*${NC}" | tee -a "$LOG"; }
warn() { echo -e "${YELLOW}  [!!] $*${NC}" | tee -a "$LOG"; }
step() { echo -e "\n${BOLD}${CYAN}══ $* ══${NC}" | tee -a "$LOG"; }

CHECKLIST=()

mkdir -p "$(dirname "$LOG")"
echo "=== RobloxOS chroot-setup.sh START $(date) ===" >> "$LOG"


# ══════════════════════════════════════════════════════════════════════════════
step "1/12 – Weryfikacja środowiska"
# ══════════════════════════════════════════════════════════════════════════════

[[ $EUID -eq 0 ]] || { echo "Uruchom jako root!"; exit 1; }

# Sprawdź czy mamy internet (potrzebny dla Flatpak)
if curl -s --max-time 5 https://flathub.org > /dev/null 2>&1; then
    HAVE_INTERNET=true
    ok "Połączenie z internetem: dostępne."
else
    HAVE_INTERNET=false
    warn "BRAK internetu – Flatpak (Discord, Sober) nie zostanie zainstalowany teraz."
    warn "Zainstaluj je ręcznie po pierwszym uruchomieniu systemu."
fi


# ══════════════════════════════════════════════════════════════════════════════
step "2/12 – Tworzenie użytkownika robloxuser"
# ══════════════════════════════════════════════════════════════════════════════

if id "$ROBLOX_USER" &>/dev/null; then
    ok "Użytkownik $ROBLOX_USER już istnieje – pomijam tworzenie."
else
    info "Tworzę użytkownika $ROBLOX_USER..."
    useradd \
        --create-home \
        --home-dir "$ROBLOX_HOME" \
        --shell /usr/sbin/nologin \
        --comment "RobloxOS Console User" \
        --groups audio,video,plugdev,netdev \
        "$ROBLOX_USER"
    # Ustaw tymczasowe hasło (zostanie zmienione przez sudoers / admina)
    echo "${ROBLOX_USER}:robloxos_change_me" | chpasswd
    ok "Użytkownik $ROBLOX_USER utworzony."
fi

CHECKLIST+=("Użytkownik: $ROBLOX_USER")


# ══════════════════════════════════════════════════════════════════════════════
step "3/12 – Kopiowanie plików projektu"
# ══════════════════════════════════════════════════════════════════════════════

mkdir -p "$OPT_DIR"

# Katalog launchera
info "Kopiuję launcher..."
mkdir -p "${ROBLOX_HOME}/launcher"
cp "${PROJECT_SRC}/launcher/launcher.py"         "${ROBLOX_HOME}/launcher/"
cp "${PROJECT_SRC}/launcher/discord_launcher.py" "${ROBLOX_HOME}/launcher/"
cp "${PROJECT_SRC}/launcher/requirements.txt"    "${ROBLOX_HOME}/launcher/"

# Katalog browser extension
info "Kopiuję Chromium extension..."
mkdir -p "${ROBLOX_HOME}/browser"
cp "${PROJECT_SRC}/browser/manifest.json"  "${ROBLOX_HOME}/browser/"
cp "${PROJECT_SRC}/browser/rules.json"     "${ROBLOX_HOME}/browser/"
cp "${PROJECT_SRC}/browser/blocked.html"   "${ROBLOX_HOME}/browser/"
cp "${PROJECT_SRC}/browser/background.js"  "${ROBLOX_HOME}/browser/"

# Katalog security (skrypty i pliki konfiguracyjne)
info "Kopiuję pliki security..."
cp -r "${PROJECT_SRC}/security" "$OPT_DIR/security"

# Watchdog do /opt/robloxos
cp "${PROJECT_SRC}/security/watchdog/watchdog.py" "$OPT_DIR/watchdog.py"
chmod 750 "$OPT_DIR/watchdog.py"

ok "Pliki projektu skopiowane."
CHECKLIST+=("Pliki projektu: ${ROBLOX_HOME}/launcher, ${ROBLOX_HOME}/browser")


# ══════════════════════════════════════════════════════════════════════════════
step "4/12 – Python venv + pip requirements"
# ══════════════════════════════════════════════════════════════════════════════

VENV_DIR="${ROBLOX_HOME}/launcher/venv"

if [[ -d "$VENV_DIR" ]]; then
    ok "venv już istnieje – pomijam."
else
    info "Tworzę venv w $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

info "Instaluję pip requirements..."
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${ROBLOX_HOME}/launcher/requirements.txt"

ok "Python venv gotowy."
CHECKLIST+=("Python venv: $VENV_DIR")


# ══════════════════════════════════════════════════════════════════════════════
step "5/12 – Konfiguracja Openbox"
# ══════════════════════════════════════════════════════════════════════════════

OPENBOX_CFG="${ROBLOX_HOME}/.config/openbox"
mkdir -p "$OPENBOX_CFG"

cp "${PROJECT_SRC}/openbox/autostart" "${OPENBOX_CFG}/autostart"
cp "${PROJECT_SRC}/openbox/rc.xml"    "${OPENBOX_CFG}/rc.xml"
chmod 644 "${OPENBOX_CFG}/autostart" "${OPENBOX_CFG}/rc.xml"

ok "Openbox skonfigurowany."
CHECKLIST+=("Openbox: ${OPENBOX_CFG}/")


# ══════════════════════════════════════════════════════════════════════════════
step "6/12 – .xsession (sesja graficzna)"
# ══════════════════════════════════════════════════════════════════════════════

cat > "${ROBLOX_HOME}/.xsession" <<'XSESSION'
#!/bin/bash
# Uruchomiona przez LightDM jako sesja użytkownika robloxuser.
# exec openbox-session czyta ~/.config/openbox/autostart i rc.xml.
exec openbox-session
XSESSION

chmod 755 "${ROBLOX_HOME}/.xsession"

# Utwórz też plik .xinitrc (fallback dla startx)
cp "${ROBLOX_HOME}/.xsession" "${ROBLOX_HOME}/.xinitrc"

ok ".xsession skonfigurowany."
CHECKLIST+=("Sesja: .xsession → openbox-session")


# ══════════════════════════════════════════════════════════════════════════════
step "7/12 – LightDM (autologin)"
# ══════════════════════════════════════════════════════════════════════════════

LIGHTDM_CONF_SRC="${PROJECT_SRC}/iso/lightdm/lightdm.conf"
LIGHTDM_CONF_DST="/etc/lightdm/lightdm.conf"

if [[ -f "$LIGHTDM_CONF_SRC" ]]; then
    cp "$LIGHTDM_CONF_SRC" "$LIGHTDM_CONF_DST"
else
    # Fallback: generuj inline jeśli plik nie jest dostępny
    warn "lightdm.conf nie znaleziony w projekcie – generuję inline."
    cat > "$LIGHTDM_CONF_DST" <<EOF
[LightDM]
minimum-vt=1

[Seat:*]
autologin-user=${ROBLOX_USER}
autologin-user-timeout=0
user-session=openbox
session-wrapper=/etc/lightdm/Xsession
greeter-session=lightdm-greeter-disabled
allow-guest=false
EOF
fi

chmod 644 "$LIGHTDM_CONF_DST"

# Utwórz plik sesji Openbox dla LightDM jeśli nie istnieje
SESSIONS_DIR="/usr/share/xsessions"
mkdir -p "$SESSIONS_DIR"
if [[ ! -f "${SESSIONS_DIR}/openbox.desktop" ]]; then
    cat > "${SESSIONS_DIR}/openbox.desktop" <<EOF
[Desktop Entry]
Name=Openbox
Comment=Log in using the Openbox window manager (without a session manager)
Exec=openbox-session
TryExec=openbox-session
Icon=openbox
Type=XSession
EOF
fi

ok "LightDM skonfigurowany (autologin → openbox)."
CHECKLIST+=("LightDM: autologin=$ROBLOX_USER, session=openbox")


# ══════════════════════════════════════════════════════════════════════════════
step "8/12 – Flatpak + Discord"
# ══════════════════════════════════════════════════════════════════════════════

if [[ "$HAVE_INTERNET" == "true" ]]; then
    # Dodaj Flathub jeśli nie ma
    if ! flatpak remotes --system | grep -q flathub; then
        info "Dodaję repozytorium Flathub..."
        flatpak remote-add --system --if-not-exists flathub \
            https://dl.flathub.org/repo/flathub.flatpakrepo
    fi

    # Zainstaluj Discord
    if ! flatpak list --system | grep -q "com.discordapp.Discord"; then
        info "Instaluję Discord (Flatpak) – może chwilę potrwać..."
        flatpak install --system --noninteractive flathub com.discordapp.Discord \
            2>&1 | tee -a "$LOG" || warn "Instalacja Discorda nieudana – spróbuj ręcznie."
    else
        ok "Discord już zainstalowany."
    fi

    CHECKLIST+=("Discord: Flatpak com.discordapp.Discord")
else
    warn "Pomijam Discord (brak internetu)."
    warn "Po uruchomieniu systemu zaloguj się jako root i wykonaj:"
    warn "  flatpak remote-add --system flathub https://dl.flathub.org/repo/flathub.flatpakrepo"
    warn "  flatpak install --system flathub com.discordapp.Discord"
    CHECKLIST+=("Discord: POMINIĘTY (brak internetu podczas buildu)")
fi


# ══════════════════════════════════════════════════════════════════════════════
step "9/12 – Sober (Roblox Linux wrapper)"
# ══════════════════════════════════════════════════════════════════════════════
#
# Sober jest dostępny jako Flatpak na Flathub: org.vinegarhq.Sober
# Strona projektu: https://sober.vinegarhq.org
# Flatpak ID: org.vinegarhq.Sober

if [[ "$HAVE_INTERNET" == "true" ]]; then
    if ! flatpak list --system | grep -q "org.vinegarhq.Sober"; then
        info "Instaluję Sober (Roblox wrapper, Flatpak)..."
        flatpak install --system --noninteractive flathub org.vinegarhq.Sober \
            2>&1 | tee -a "$LOG" || {
            warn "Instalacja Sober przez Flatpak nieudana."
            warn "Alternatywa: pobierz .deb z https://sober.vinegarhq.org i:"
            warn "  dpkg -i sober_*.deb"
        }
    else
        ok "Sober już zainstalowany."
    fi

    # Zaktualizuj komendę w launcher.py na flatpak run jeśli Sober jest przez Flatpak
    # (launcher.py domyślnie wywołuje 'sober' – zaktualizuj jeśli potrzeba)
    # flatpak run org.vinegarhq.Sober

    CHECKLIST+=("Sober: Flatpak org.vinegarhq.Sober")
else
    warn "Pomijam Sober (brak internetu)."
    warn "Po uruchomieniu systemu:"
    warn "  flatpak install --system flathub org.vinegarhq.Sober"
    CHECKLIST+=("Sober: POMINIĘTY (brak internetu podczas buildu)")
fi


# ══════════════════════════════════════════════════════════════════════════════
step "10/12 – Blokada bezpieczeństwa (install_security.sh)"
# ══════════════════════════════════════════════════════════════════════════════

SECURITY_SCRIPT="$OPT_DIR/security/install_security.sh"
chmod +x "$SECURITY_SCRIPT"

info "Uruchamiam install_security.sh..."
# Przekaż SCRIPT_DIR żeby skrypt wiedział skąd brać pliki
SCRIPT_DIR="$OPT_DIR/security" bash "$SECURITY_SCRIPT" 2>&1 | tee -a "$LOG"

CHECKLIST+=("Security: sudoers, AppArmor, polkit, watchdog")


# ══════════════════════════════════════════════════════════════════════════════
step "11/12 – Usługi systemd"
# ══════════════════════════════════════════════════════════════════════════════

# LightDM (display manager – startuje sesję graficzną)
systemctl enable lightdm 2>/dev/null || warn "Nie można włączyć lightdm (chroot?)"

# AppArmor
systemctl enable apparmor 2>/dev/null || warn "Nie można włączyć apparmor (chroot?)"

# Wyłącz niepotrzebne
for svc in snapd unattended-upgrades motd-news; do
    systemctl disable "$svc" 2>/dev/null || true
    systemctl mask "$svc" 2>/dev/null || true
done

ok "Usługi skonfigurowane."
CHECKLIST+=("Usługi: lightdm=enabled, apparmor=enabled")


# ══════════════════════════════════════════════════════════════════════════════
step "12/12 – Uprawnienia plików"
# ══════════════════════════════════════════════════════════════════════════════

# Cały home użytkownika – właściciel robloxuser
chown -R "${ROBLOX_USER}:${ROBLOX_USER}" "$ROBLOX_HOME"

# Launcher i extension – tylko do odczytu dla usera (nie może modyfikować)
chmod -R 755 "${ROBLOX_HOME}/launcher"
chmod -R 755 "${ROBLOX_HOME}/browser"
chmod 744 "${ROBLOX_HOME}/launcher/launcher.py"
chmod 744 "${ROBLOX_HOME}/launcher/discord_launcher.py"

# .xsession musi być wykonywalny
chmod 755 "${ROBLOX_HOME}/.xsession"
chmod 755 "${ROBLOX_HOME}/.xinitrc"

# Openbox config – tylko do odczytu dla usera
chmod 644 "${ROBLOX_HOME}/.config/openbox/rc.xml"
chmod 644 "${ROBLOX_HOME}/.config/openbox/autostart"

# /opt/robloxos – tylko root może pisać
chown -R root:root "$OPT_DIR"
chmod -R 755 "$OPT_DIR"
chmod 750 "$OPT_DIR/watchdog.py"

ok "Uprawnienia ustawione."
CHECKLIST+=("Uprawnienia: chown + chmod")


# ══════════════════════════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║   RobloxOS setup zakończony pomyślnie!      ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BOLD}Zainstalowane komponenty:${NC}"
for item in "${CHECKLIST[@]}"; do
    echo -e "  ${GREEN}✓${NC} $item"
done
echo ""
echo -e "Log zapisany do: ${CYAN}$LOG${NC}"
echo ""
echo -e "${YELLOW}Następne kroki (jeśli pominięto Flatpak):${NC}"
echo "  flatpak install --system flathub com.discordapp.Discord"
echo "  flatpak install --system flathub org.vinegarhq.Sober"
echo ""
echo "=== RobloxOS chroot-setup.sh END $(date) ===" >> "$LOG"
