#!/usr/bin/env bash
# RobloxOS – Read-only rootfs z overlayfs
#
# Po konfiguracji:
#   - / jest read-only (zmiany nie przeżywają restartu)
#   - tmpfs overlay na /tmp, /var, /home/robloxuser (reset przy restarcie)
#   - Persistent (przeżywają restart): /etc/robloxos, /var/lib/robloxos
#
# Uruchom jako root po zainstalowaniu systemu.
# UWAGA: Po włączeniu musisz mieć dostęp przez SSH/TTY jako root
#        żeby modyfikować system.

set -euo pipefail

PERSIST_PARTITION=""  # np. /dev/sda3 – ustaw ręcznie lub pozostaw puste (tmpfs)
PERSIST_MOUNT="/mnt/robloxos-persist"
FSTAB="/etc/fstab"
INITRAMFS_HOOK="/etc/initramfs-tools/scripts/init-bottom/robloxos-overlay"
LOG="/var/log/robloxos-setup.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  [OK]${NC} $*" | tee -a "$LOG"; }
info() { echo -e "${CYAN}  [..] $*${NC}" | tee -a "$LOG"; }
warn() { echo -e "${YELLOW}  [!!] $*${NC}" | tee -a "$LOG"; }
fail() { echo -e "${RED}  [✗] $*${NC}" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Uruchom jako root."

CMD="${1:-help}"

# ══════════════════════════════════════════════════════════════════════════════
setup_overlay() {
# ══════════════════════════════════════════════════════════════════════════════
    info "Instaluję overlayfs (read-only rootfs)..."

    # 1. Zainstaluj overlayroot jeśli dostępny
    if apt-get install -y -qq overlayroot 2>/dev/null; then
        info "overlayroot zainstalowany."
        _setup_via_overlayroot
    else
        warn "overlayroot niedostępny – konfiguracja przez initramfs hook."
        _setup_via_initramfs
    fi
}

_setup_via_overlayroot() {
    # overlayroot to Ubuntu-specific narzędzie upraszczające konfigurację
    local overlayroot_conf="/etc/overlayroot.conf"

    # Backup config
    [[ -f "$overlayroot_conf" ]] && cp "$overlayroot_conf" "${overlayroot_conf}.bak"

    cat > "$overlayroot_conf" <<'EOF'
# RobloxOS overlayroot configuration
# tmpfs: overlay w RAM (reset przy restarcie)
# recurse=0: tylko / jest read-only, nie /boot
overlayroot="tmpfs:recurse=0"

# Opcje tmpfs
overlayroot_cfgdisk="LABEL=robloxos-persist"
EOF

    # Ustaw wyjątki (persistent paths)
    _configure_persistent_paths

    # Przebuduj initramfs
    info "Przebudowuję initramfs..."
    update-initramfs -u -k all 2>> "$LOG"

    ok "overlayroot skonfigurowany. Restart = read-only rootfs aktywny."
    warn "UWAGA: Po restarcie zmiany w / nie przeżyją kolejnego restartu."
    warn "Administracja: dodaj 'overlayroot-chroot' przed komendami modyfikującymi system."
}

_setup_via_initramfs() {
    # Ręczna konfiguracja przez hook initramfs

    mkdir -p "$(dirname "$INITRAMFS_HOOK")"
    cat > "$INITRAMFS_HOOK" <<'HOOK'
#!/bin/sh
# RobloxOS overlayfs init-bottom hook
# Tworzy overlay na rootfs zanim /sbin/init się uruchomi.
PREREQ=""
prereqs() { echo "$PREREQ"; }
case "$1" in prereqs) prereqs; exit 0;; esac

. /scripts/functions

OVERLAY_DIR="/run/robloxos-overlay"
mkdir -p "${OVERLAY_DIR}/upper" "${OVERLAY_DIR}/work"

# Podmontuj rootfs jako read-only
mount -o remount,ro "${rootmnt}" 2>/dev/null || true

# Utwórz tmpfs overlay
mount -t tmpfs -o size=512m tmpfs "${OVERLAY_DIR}"
mkdir -p "${OVERLAY_DIR}/upper" "${OVERLAY_DIR}/work"

# Overlay na rootfs
mount -t overlay overlay \
    -o "lowerdir=${rootmnt},upperdir=${OVERLAY_DIR}/upper,workdir=${OVERLAY_DIR}/work" \
    "${rootmnt}"

log_success_msg "RobloxOS overlayfs aktywny"
HOOK

    chmod +x "$INITRAMFS_HOOK"
    update-initramfs -u -k all 2>> "$LOG"
    ok "Initramfs hook zainstalowany."
}

# ══════════════════════════════════════════════════════════════════════════════
_configure_persistent_paths() {
# ══════════════════════════════════════════════════════════════════════════════
    # Bind-mount persistent katalogów z osobnej partycji lub tmpfs
    # na katalogi które muszą przeżywać restart.

    local persist_dirs=(
        "/etc/robloxos"           # konfiguracja
        "/var/lib/robloxos"       # stan sesji, OTA state
        "/var/log"                # logi
        "/var/lib/flatpak"        # flatpak (Discord, Sober)
        "/home/robloxuser/.var"   # flatpak user data
    )

    info "Konfiguruję persistent bind-mounts..."

    # Utwórz backup katalogu dla persistent danych
    mkdir -p "$PERSIST_MOUNT"

    for dir in "${persist_dirs[@]}"; do
        local persist_path="${PERSIST_MOUNT}${dir}"
        mkdir -p "$persist_path"
        # Skopiuj aktualne dane
        [[ -d "$dir" ]] && rsync -a "${dir}/" "${persist_path}/" 2>/dev/null || true
    done

    # Dodaj do /etc/fstab jeśli persist partition jest ustawiony
    if [[ -n "$PERSIST_PARTITION" ]]; then
        if ! grep -q "robloxos-persist" "$FSTAB"; then
            cat >> "$FSTAB" <<EOF

# RobloxOS persistent storage
${PERSIST_PARTITION}  ${PERSIST_MOUNT}  ext4  defaults,noatime  0  2
EOF
            for dir in "${persist_dirs[@]}"; do
                echo "${PERSIST_MOUNT}${dir}  ${dir}  none  bind  0  0" >> "$FSTAB"
            done
            ok "Persistent bind-mounts dodane do /etc/fstab."
        fi
    else
        warn "PERSIST_PARTITION nie ustawiony – persistent dane będą na tmpfs (resetowane przy restarcie)."
        warn "Ustaw PERSIST_PARTITION w skrypcie na np. /dev/sda3."
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
install_reset_script() {
# ══════════════════════════════════════════════════════════════════════════════
    cat > /usr/local/bin/robloxos-reset <<'RESET'
#!/usr/bin/env bash
# Czyści overlay bez restartu (wymaga root).
# Usuwa wszystkie zmiany wprowadzone przez robloxusera w bieżącej sesji.
set -e
if [[ $EUID -ne 0 ]]; then echo "Wymaga root."; exit 1; fi
OVERLAY_DIR="/run/robloxos-overlay"
if [[ -d "${OVERLAY_DIR}/upper" ]]; then
    rm -rf "${OVERLAY_DIR}/upper"/*
    echo "Overlay wyczyszczony. Zmiany cofnięte."
else
    echo "Overlay nie jest aktywny."
fi
RESET
    chmod +x /usr/local/bin/robloxos-reset
    ok "Skrypt reset: /usr/local/bin/robloxos-reset"
}

# ══════════════════════════════════════════════════════════════════════════════
status_overlay() {
# ══════════════════════════════════════════════════════════════════════════════
    echo -e "\n${CYAN}Status overlayfs:${NC}"
    if mount | grep -q "overlay on /"; then
        ok "overlayfs AKTYWNY na /"
        mount | grep "overlay on /" || true
    else
        warn "overlayfs NIE jest aktywny (tryb normalny – zmiany są trwałe)"
    fi

    echo ""
    echo "Punkty montowania persistent:"
    mount | grep bind | grep robloxos || echo "  (brak)"
}

# ══════════════════════════════════════════════════════════════════════════════
case "$CMD" in
    setup)  setup_overlay; install_reset_script ;;
    status) status_overlay ;;
    reset)  /usr/local/bin/robloxos-reset 2>/dev/null || install_reset_script && /usr/local/bin/robloxos-reset ;;
    help|*)
        echo "Użycie: $0 [setup|status|reset]"
        echo ""
        echo "  setup   Włącz read-only rootfs z overlayfs"
        echo "  status  Sprawdź czy overlayfs jest aktywny"
        echo "  reset   Wyczyść overlay (cofnij zmiany sesji)"
        ;;
esac
