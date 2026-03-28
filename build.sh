#!/usr/bin/env bash
# RobloxOS build.sh – jeden skrypt buduje wszystko
#
# Tryby:
#   ./build.sh --live        Instalacja na bieżącym systemie (bez ISO)
#   ./build.sh --iso         Pełny pipeline: pobierz base ISO → zbuduj custom ISO
#   ./build.sh --iso --test  Jak wyżej + test w QEMU po budowie
#   ./build.sh --vm          Tryb VM: AppArmor=complain, instalacja guest-utils
#
# Wymagania: Ubuntu 22.04, root, ~20 GB wolnego miejsca (tryb --iso)

set -euo pipefail
IFS=$'\n\t'
export DEBIAN_FRONTEND=noninteractive

# ══════════════════════════════════════════════════════════════════════════════
# KONFIGURACJA
# ══════════════════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="robloxos"
VERSION="2.0"
ROBLOX_USER="robloxuser"
ROBLOX_HOME="/home/${ROBLOX_USER}"
OPT_DIR="/opt/robloxos"
CONFIG_DIR="/etc/robloxos"
STATE_DIR="/var/lib/robloxos"
LOG_DIR="/var/log"

# ISO build vars
BUILD_DIR="${SCRIPT_DIR}/build"
OUTPUT_DIR="${SCRIPT_DIR}/output"
BASE_ISO_URL="https://releases.ubuntu.com/22.04/ubuntu-22.04.4-desktop-amd64.iso"
BASE_ISO_SHA256="45f873de9f8cb637345d6e66a583762730bbea30277ef7b32c9c3bd6700a32b"
BASE_ISO_NAME="ubuntu-22.04.4-desktop-amd64.iso"
WORK_DIR="${BUILD_DIR}/iso-work"
SQUASH_DIR="${BUILD_DIR}/squashfs-root"
OUTPUT_ISO="${OUTPUT_DIR}/${PROJECT_NAME}-${VERSION}-amd64.iso"

# Flagi
MODE_LIVE=false
MODE_ISO=false
MODE_TEST=false
MODE_VM=false

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}  ✓${NC} $*"; }
warn() { echo -e "${YELLOW}  ⚠${NC} $*"; }
fail() { echo -e "${RED}  ✗ BŁĄD: $*${NC}" >&2; exit 1; }
step() { echo -e "\n${BOLD}${CYAN}━━━ $* ━━━${NC}"; }

cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        warn "Build przerwany (exit code: $exit_code)"
        # Odmontuj jeśli coś zostało podmontowane
        if mountpoint -q "${WORK_DIR}/squashfs-root" 2>/dev/null; then
            umount "${WORK_DIR}/squashfs-root" 2>/dev/null || true
        fi
        for dir in proc sys dev/pts dev run; do
            if mountpoint -q "${SQUASH_DIR}/${dir}" 2>/dev/null; then
                umount "${SQUASH_DIR}/${dir}" 2>/dev/null || true
            fi
        done
    fi
}
trap cleanup EXIT

# ══════════════════════════════════════════════════════════════════════════════
# PARSOWANIE ARGUMENTÓW
# ══════════════════════════════════════════════════════════════════════════════

if [[ $# -eq 0 ]]; then
    echo "Użycie: $0 [--live] [--iso] [--test] [--vm]"
    echo "  --live   Instaluj na bieżącym systemie"
    echo "  --iso    Zbuduj instalacyjny ISO"
    echo "  --test   Uruchom ISO w QEMU po zbudowaniu"
    echo "  --vm     Tryb VirtualBox (AppArmor complain, guest-utils)"
    exit 0
fi

for arg in "$@"; do
    case "$arg" in
        --live) MODE_LIVE=true ;;
        --iso)  MODE_ISO=true  ;;
        --test) MODE_TEST=true ;;
        --vm)   MODE_VM=true   ;;
        *) fail "Nieznany argument: $arg" ;;
    esac
done

[[ "$MODE_LIVE" == "false" && "$MODE_ISO" == "false" ]] && \
    fail "Podaj tryb: --live lub --iso"

# ══════════════════════════════════════════════════════════════════════════════
# WERYFIKACJA ŚRODOWISKA
# ══════════════════════════════════════════════════════════════════════════════

step "Weryfikacja środowiska"

[[ $EUID -eq 0 ]] || fail "Uruchom jako root: sudo $0 $*"

# Sprawdź OS
if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    if [[ "$ID" != "ubuntu" || "$VERSION_ID" != "22.04" ]]; then
        warn "Wykryto: $PRETTY_NAME (zalecane: Ubuntu 22.04 LTS)"
        warn "Kontynuuję – mogą pojawić się błędy pakietów."
    else
        ok "System: $PRETTY_NAME"
    fi
fi

# Wykryj VM
VIRT_TYPE="none"
if command -v systemd-detect-virt &>/dev/null; then
    VIRT_TYPE=$(systemd-detect-virt 2>/dev/null || echo "none")
fi
if [[ "$VIRT_TYPE" != "none" ]]; then
    warn "Środowisko wirtualne wykryte: ${VIRT_TYPE}"
    MODE_VM=true
fi

[[ "$MODE_VM" == "true" ]] && ok "Tryb VM aktywny"

# Sprawdź wolne miejsce
if [[ "$MODE_ISO" == "true" ]]; then
    AVAIL_KB=$(df -k "${SCRIPT_DIR}" | tail -1 | awk '{print $4}')
    AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
    [[ $AVAIL_GB -ge 18 ]] || fail "Za mało miejsca: ${AVAIL_GB} GB (potrzeba ≥18 GB)"
    ok "Wolne miejsce: ${AVAIL_GB} GB"
fi

log "Tryb: $([ "$MODE_LIVE" = "true" ] && echo "LIVE") $([ "$MODE_ISO" = "true" ] && echo "ISO") $([ "$MODE_VM" = "true" ] && echo "VM")"

# ══════════════════════════════════════════════════════════════════════════════
# FUNKCJA: INSTALACJA NA ŻYWYM SYSTEMIE
# ══════════════════════════════════════════════════════════════════════════════

install_live() {
    step "1/8 – Instalacja pakietów apt"
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        xorg openbox lightdm picom unclutter wmctrl x11-xserver-utils xdotool \
        python3 python3-pip python3-venv python3-pyqt6 python3-psutil \
        chromium-browser flatpak \
        apparmor apparmor-utils apparmor-profiles \
        curl wget git ca-certificates gnupg \
        pulseaudio fonts-ubuntu fonts-noto-color-emoji \
        logrotate net-tools iproute2
    ok "Pakiety zainstalowane."

    if [[ "$MODE_VM" == "true" ]]; then
        log "VM: instaluję virtualbox-guest-utils..."
        apt-get install -y --no-install-recommends \
            virtualbox-guest-utils virtualbox-guest-x11 2>/dev/null || \
            warn "virtualbox-guest-utils niedostępne – zainstaluj sterowniki VM ręcznie."
    fi

    step "2/8 – Tworzenie użytkownika ${ROBLOX_USER}"
    if ! id "$ROBLOX_USER" &>/dev/null; then
        useradd --create-home --home-dir "$ROBLOX_HOME" \
                --shell /usr/sbin/nologin \
                --comment "RobloxOS Console User" \
                --groups audio,video,netdev \
                "$ROBLOX_USER"
        echo "${ROBLOX_USER}:robloxos_change_me" | chpasswd
        ok "Użytkownik ${ROBLOX_USER} utworzony."
    else
        ok "Użytkownik ${ROBLOX_USER} już istnieje."
    fi

    step "3/8 – Katalogi systemowe"
    mkdir -p "$OPT_DIR" "$CONFIG_DIR" "$STATE_DIR"
    chmod 755 "$OPT_DIR" "$CONFIG_DIR"
    chmod 700 "$STATE_DIR"

    # Domyślny config.json jeśli nie istnieje
    if [[ ! -f "${CONFIG_DIR}/config.json" ]]; then
        cat > "${CONFIG_DIR}/config.json" <<'EOF'
{
  "admin_password_hash": "",
  "whitelist": [
    "roblox.com", "discord.com", "discordapp.com", "discordapp.net",
    "youtube.com", "youtu.be", "ytimg.com", "googlevideo.com",
    "googleapis.com", "gstatic.com"
  ],
  "time_limits": {
    "roblox": 120,
    "discord": 60,
    "browser": 30
  },
  "schedule": {
    "enabled": false,
    "days": [0,1,2,3,4,5,6],
    "start": "15:00",
    "end": "21:00"
  },
  "ota": {
    "enabled": false,
    "repo_url": "",
    "check_time": "03:00"
  },
  "vm_mode": false,
  "apparmor_mode": "enforce"
}
EOF
        chmod 640 "${CONFIG_DIR}/config.json"
        chown root:root "${CONFIG_DIR}/config.json"
    fi

    # session_times.json
    if [[ ! -f "${STATE_DIR}/session_times.json" ]]; then
        echo '{"roblox": 0, "discord": 0, "browser": 0, "date": ""}' \
            > "${STATE_DIR}/session_times.json"
        chmod 664 "${STATE_DIR}/session_times.json"
        chown root:"$ROBLOX_USER" "${STATE_DIR}/session_times.json"
    fi

    step "4/8 – Kopiowanie plików projektu"
    _copy_project_files

    step "5/8 – Python venv"
    _setup_venv

    step "6/8 – Konfiguracja systemu"
    _configure_system

    step "7/8 – Blokady bezpieczeństwa"
    _apply_security

    step "8/8 – Logrotate"
    _setup_logrotate

    ok "Instalacja na żywym systemie zakończona."
}

# ══════════════════════════════════════════════════════════════════════════════
# FUNKCJA: BUDOWANIE ISO
# ══════════════════════════════════════════════════════════════════════════════

build_iso() {
    step "ISO 1/7 – Pobieranie bazowego Ubuntu 22.04 ISO"
    mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"

    local base_iso="${BUILD_DIR}/${BASE_ISO_NAME}"
    if [[ -f "$base_iso" ]]; then
        log "ISO już pobrany – weryfikuję sumę..."
    else
        log "Pobieram ${BASE_ISO_URL}..."
        wget --show-progress -q -c -O "$base_iso" "$BASE_ISO_URL"
    fi

    # Weryfikacja SHA256
    echo "${BASE_ISO_SHA256}  ${base_iso}" | sha256sum -c - || \
        fail "Błędna suma kontrolna ISO! Usuń ${base_iso} i spróbuj ponownie."
    ok "ISO zweryfikowany."

    step "ISO 2/7 – Ekstrakcja zawartości ISO"
    mkdir -p "$WORK_DIR"
    if [[ -d "${WORK_DIR}/casper" ]]; then
        log "Praca już wypakowana – pomijam ekstrakcję."
    else
        log "Wypakuję ISO (może potrwać ~3 minuty)..."
        xorriso -osirrox on \
            -indev "$base_iso" \
            -extract / "$WORK_DIR" 2>/dev/null
    fi
    ok "ISO wypakowany do ${WORK_DIR}."

    step "ISO 3/7 – Wypakowanie squashfs"
    if [[ -d "$SQUASH_DIR" ]]; then
        log "squashfs już wypakowany – pomijam."
    else
        log "Wypakuję filesystem.squashfs (może potrwać ~5 minut)..."
        unsquashfs -d "$SQUASH_DIR" "${WORK_DIR}/casper/filesystem.squashfs"
    fi
    ok "squashfs wypakowany."

    step "ISO 4/7 – Kopiowanie plików projektu do squashfs"
    # Skopiuj projekt do squashfs
    mkdir -p "${SQUASH_DIR}/tmp/robloxos"
    cp -r "${SCRIPT_DIR}/launcher"  "${SQUASH_DIR}/tmp/robloxos/"
    cp -r "${SCRIPT_DIR}/openbox"   "${SQUASH_DIR}/tmp/robloxos/"
    cp -r "${SCRIPT_DIR}/browser"   "${SQUASH_DIR}/tmp/robloxos/"
    cp -r "${SCRIPT_DIR}/security"  "${SQUASH_DIR}/tmp/robloxos/"
    cp -r "${SCRIPT_DIR}/updater"   "${SQUASH_DIR}/tmp/robloxos/" 2>/dev/null || true
    cp -r "${SCRIPT_DIR}/admin"     "${SQUASH_DIR}/tmp/robloxos/" 2>/dev/null || true
    cp -r "${SCRIPT_DIR}/overlay"   "${SQUASH_DIR}/tmp/robloxos/" 2>/dev/null || true
    cp -r "${SCRIPT_DIR}/webpanel"  "${SQUASH_DIR}/tmp/robloxos/" 2>/dev/null || true
    cp    "${SCRIPT_DIR}/iso/chroot-setup.sh" "${SQUASH_DIR}/tmp/"
    chmod +x "${SQUASH_DIR}/tmp/chroot-setup.sh"
    ok "Pliki projektu skopiowane."

    step "ISO 5/7 – Chroot: instalacja i konfiguracja"
    _chroot_exec "$SQUASH_DIR"
    ok "Chroot setup zakończony."

    step "ISO 6/7 – Przepakowanie squashfs"
    log "Pakuję squashfs (xz, może potrwać ~10 minut)..."
    rm -f "${WORK_DIR}/casper/filesystem.squashfs"
    mksquashfs "$SQUASH_DIR" "${WORK_DIR}/casper/filesystem.squashfs" \
        -comp xz -Xbcj x86 -b 1048576 -noappend \
        2>&1 | tail -3
    # Zaktualizuj manifest i rozmiar
    chroot "$SQUASH_DIR" dpkg-query -W --showformat='${Package} ${Version}\n' \
        > "${WORK_DIR}/casper/filesystem.manifest" 2>/dev/null || true
    printf $(du -sx --block-size=1 "$SQUASH_DIR" | cut -f1) \
        > "${WORK_DIR}/casper/filesystem.size"
    ok "squashfs przepakowany: $(du -sh "${WORK_DIR}/casper/filesystem.squashfs" | cut -f1)"

    step "ISO 7/7 – Budowanie ISO"
    log "Buduję ${OUTPUT_ISO}..."
    # Dodaj preseed autoinstall
    mkdir -p "${WORK_DIR}/autoinstall"
    cp "${SCRIPT_DIR}/iso/preseed/user-data" "${WORK_DIR}/autoinstall/"
    cp "${SCRIPT_DIR}/iso/preseed/meta-data" "${WORK_DIR}/autoinstall/"
    # Zaktualizuj sumę md5
    find "$WORK_DIR" -type f -not -path "*/\[BOOT\]/*" \
        -exec md5sum {} \; | sed "s|${WORK_DIR}/||" > "${WORK_DIR}/md5sum.txt"
    # Zbuduj ISO (UEFI + BIOS)
    xorriso -as mkisofs \
        -r -V "RobloxOS ${VERSION}" \
        -o "$OUTPUT_ISO" \
        -J -joliet-long \
        --grub2-mbr "${WORK_DIR}/boot/grub/i386-pc/boot_hybrid.img" \
        -partition_offset 16 \
        --mbr-force-bootable \
        -append_partition 2 28732ac11ff8d211ba4b00a0c93ec93b \
            "${WORK_DIR}/boot/grub/efi.img" \
        -appended_part_as_gpt \
        -iso_mbr_part_type a2a0d0ebe5b9334487c068b6b72699c7 \
        -b boot/grub/i386-pc/eltorito.img \
        -c boot.catalog \
        -no-emul-boot -boot-load-size 4 -boot-info-table --grub2-boot-info \
        -eltorito-alt-boot \
        -e '--interval:appended_partition_2:::' \
        -no-emul-boot \
        "$WORK_DIR" 2>&1 | tail -5

    local iso_size
    iso_size=$(du -sh "$OUTPUT_ISO" | cut -f1)
    local iso_sha256
    iso_sha256=$(sha256sum "$OUTPUT_ISO" | cut -d' ' -f1)

    echo ""
    echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${BOLD}${GREEN}║  ISO zbudowany pomyślnie!                           ║${NC}"
    echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
    echo -e "  Plik:    ${CYAN}${OUTPUT_ISO}${NC}"
    echo -e "  Rozmiar: ${iso_size}"
    echo -e "  SHA256:  ${iso_sha256}"
    echo ""
    echo "$iso_sha256  $(basename "$OUTPUT_ISO")" > "${OUTPUT_DIR}/SHA256SUMS"
}

_chroot_exec() {
    local root="$1"
    # Montuj pseudo-filesystemy
    mount --bind /dev     "${root}/dev"
    mount --bind /dev/pts "${root}/dev/pts"
    mount -t proc  proc  "${root}/proc"
    mount -t sysfs sysfs "${root}/sys"
    mount -t tmpfs tmpfs "${root}/run"
    # Sieć wewnątrz chroot
    cp /etc/resolv.conf "${root}/etc/resolv.conf"

    # Uruchom setup wewnątrz chroot
    chroot "$root" bash /tmp/chroot-setup.sh || warn "chroot-setup.sh zakończony z błędem – sprawdź logi."

    # Odmontuj
    for dir in run sys proc dev/pts dev; do
        umount "${root}/${dir}" 2>/dev/null || true
    done
}

# ══════════════════════════════════════════════════════════════════════════════
# POMOCNICZE FUNKCJE INSTALACYJNE
# ══════════════════════════════════════════════════════════════════════════════

_copy_project_files() {
    mkdir -p "${ROBLOX_HOME}/launcher" "${ROBLOX_HOME}/browser" \
             "${ROBLOX_HOME}/.config/openbox"

    cp "${SCRIPT_DIR}/launcher/launcher.py"          "${ROBLOX_HOME}/launcher/"
    cp "${SCRIPT_DIR}/launcher/discord_launcher.py"  "${ROBLOX_HOME}/launcher/"
    cp "${SCRIPT_DIR}/launcher/session_timer.py"     "${ROBLOX_HOME}/launcher/" 2>/dev/null || true
    cp "${SCRIPT_DIR}/launcher/requirements.txt"     "${ROBLOX_HOME}/launcher/"
    cp "${SCRIPT_DIR}/browser/manifest.json"         "${ROBLOX_HOME}/browser/"
    cp "${SCRIPT_DIR}/browser/rules.json"            "${ROBLOX_HOME}/browser/"
    cp "${SCRIPT_DIR}/browser/blocked.html"          "${ROBLOX_HOME}/browser/"
    cp "${SCRIPT_DIR}/browser/background.js"         "${ROBLOX_HOME}/browser/"
    cp "${SCRIPT_DIR}/openbox/autostart"             "${ROBLOX_HOME}/.config/openbox/"
    cp "${SCRIPT_DIR}/openbox/rc.xml"                "${ROBLOX_HOME}/.config/openbox/"

    # Opcjonalne moduły v2.0
    for mod in overlay updater admin webpanel; do
        if [[ -d "${SCRIPT_DIR}/${mod}" ]]; then
            cp -r "${SCRIPT_DIR}/${mod}" "${OPT_DIR}/${mod}"
        fi
    done

    cp -r "${SCRIPT_DIR}/security" "${OPT_DIR}/security"
    cp "${SCRIPT_DIR}/security/watchdog/watchdog.py" "${OPT_DIR}/watchdog.py"

    chown -R "${ROBLOX_USER}:${ROBLOX_USER}" "$ROBLOX_HOME"
    chown -R root:root "$OPT_DIR"
    chmod -R 755 "${ROBLOX_HOME}/launcher" "${ROBLOX_HOME}/browser"
    ok "Pliki projektu skopiowane."
}

_setup_venv() {
    local venv="${ROBLOX_HOME}/launcher/venv"
    [[ -d "$venv" ]] || python3 -m venv "$venv"
    "${venv}/bin/pip" install -q --upgrade pip
    "${venv}/bin/pip" install -q -r "${ROBLOX_HOME}/launcher/requirements.txt"
    # Moduły v2.0
    for req in "${OPT_DIR}/webpanel/requirements.txt" \
               "${OPT_DIR}/admin/requirements.txt" \
               "${OPT_DIR}/overlay/requirements.txt"; do
        [[ -f "$req" ]] && "${venv}/bin/pip" install -q -r "$req" || true
    done
    chown -R "${ROBLOX_USER}:${ROBLOX_USER}" "$venv"
    ok "Python venv gotowy."
}

_configure_system() {
    # .xsession
    echo '#!/bin/bash
exec openbox-session' > "${ROBLOX_HOME}/.xsession"
    chmod 755 "${ROBLOX_HOME}/.xsession"
    chown "${ROBLOX_USER}:${ROBLOX_USER}" "${ROBLOX_HOME}/.xsession"

    # LightDM
    cp "${SCRIPT_DIR}/iso/lightdm/lightdm.conf" /etc/lightdm/lightdm.conf
    # Plik sesji openbox
    mkdir -p /usr/share/xsessions
    cat > /usr/share/xsessions/openbox.desktop <<'EOF'
[Desktop Entry]
Name=Openbox
Exec=openbox-session
TryExec=openbox-session
Type=XSession
EOF
    systemctl enable lightdm 2>/dev/null || true

    # VM: dostosuj ustawienia
    if [[ "$MODE_VM" == "true" ]]; then
        log "VM: dostosowuję konfigurację graficzną..."
        # Wyłącz picom w autostart dla VM (może powodować problemy)
        sed -i 's|^picom|# picom|' "${ROBLOX_HOME}/.config/openbox/autostart" 2>/dev/null || true
        # Zaktualizuj config.json
        if command -v python3 &>/dev/null; then
            python3 -c "
import json, sys
with open('${CONFIG_DIR}/config.json') as f: c = json.load(f)
c['vm_mode'] = True
c['apparmor_mode'] = 'complain'
with open('${CONFIG_DIR}/config.json', 'w') as f: json.dump(c, f, indent=2)
"
        fi
    fi
    ok "System skonfigurowany."
}

_apply_security() {
    local sec="${OPT_DIR}/security"
    [[ -f "${sec}/install_security.sh" ]] || fail "Brak install_security.sh"
    chmod +x "${sec}/install_security.sh"

    if [[ "$MODE_VM" == "true" ]]; then
        log "VM: AppArmor w trybie complain zamiast enforce..."
        SCRIPT_DIR="$sec" bash "${sec}/install_security.sh" 2>&1 | tail -20
        # Przełącz na complain
        for profile in "${sec}/apparmor.d/"*; do
            aa-complain "$profile" 2>/dev/null || true
        done
        ok "AppArmor: complain (tryb VM)."
    else
        SCRIPT_DIR="$sec" bash "${sec}/install_security.sh" 2>&1 | tail -20
        ok "AppArmor: enforce (produkcja)."
    fi
}

_setup_logrotate() {
    cat > /etc/logrotate.d/robloxos <<'EOF'
/var/log/robloxos-watchdog.log
/var/log/robloxos-ota.log
/var/log/robloxos-setup.log {
    weekly
    rotate 5
    compress
    delaycompress
    missingok
    notifempty
    size 10M
    create 640 root root
}
EOF
    ok "logrotate skonfigurowany."
}

# ══════════════════════════════════════════════════════════════════════════════
# QEMU TEST
# ══════════════════════════════════════════════════════════════════════════════

run_qemu_test() {
    step "Test w QEMU"
    command -v qemu-system-x86_64 &>/dev/null || \
        { apt-get install -y -qq qemu-system-x86 qemu-utils ovmf; }

    local test_disk="${BUILD_DIR}/test-disk.qcow2"
    [[ -f "$test_disk" ]] || qemu-img create -f qcow2 "$test_disk" 30G

    log "Uruchamiam QEMU z VNC na :5900..."
    log "Połącz: vncviewer localhost:5900"
    qemu-system-x86_64 \
        -name "RobloxOS ${VERSION} Test" \
        -m 4096 -smp 2 -enable-kvm \
        -drive file="$test_disk",format=qcow2 \
        -cdrom "$OUTPUT_ISO" \
        -boot d \
        -bios /usr/share/ovmf/OVMF.fd \
        -vnc :0 \
        -net nic,model=virtio -net user \
        -vga virtio \
        -daemonize \
        -pidfile "${BUILD_DIR}/qemu.pid"
    ok "QEMU uruchomiony (PID: $(cat "${BUILD_DIR}/qemu.pid"))"
    log "Zatrzymaj: kill \$(cat ${BUILD_DIR}/qemu.pid)"
}

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

echo -e "${BOLD}${CYAN}"
echo "  ██████╗  ██████╗ ██████╗ ██╗      ██████╗ ██╗  ██╗ ██████╗ ███████╗"
echo "  ██╔══██╗██╔═══██╗██╔══██╗██║     ██╔═══██╗╚██╗██╔╝██╔═══██╗██╔════╝"
echo "  ██████╔╝██║   ██║██████╔╝██║     ██║   ██║ ╚███╔╝ ██║   ██║███████╗"
echo "  ██╔══██╗██║   ██║██╔══██╗██║     ██║   ██║ ██╔██╗ ██║   ██║╚════██║"
echo "  ██║  ██║╚██████╔╝██████╔╝███████╗╚██████╔╝██╔╝ ██╗╚██████╔╝███████║"
echo "  ╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚══════╝"
echo -e "                          Build v${VERSION}${NC}"
echo ""

[[ "$MODE_LIVE" == "true" ]] && install_live
[[ "$MODE_ISO"  == "true" ]] && build_iso
[[ "$MODE_TEST" == "true" && "$MODE_ISO" == "true" ]] && run_qemu_test

echo ""
echo -e "${BOLD}${GREEN}Build zakończony pomyślnie!${NC}"
[[ "$MODE_ISO" == "true" ]] && echo -e "ISO: ${CYAN}${OUTPUT_ISO}${NC}"
