#!/usr/bin/env bash
# RobloxOS – Secure Boot setup
# Generuje własny klucz MOK, podpisuje kernel i bootloader.
#
# Uruchom jako root na zainstalowanym systemie (NIE podczas budowania ISO).
# Wymagania: sbsign, openssl, mokutil, efitools
#
# Kroki:
#   1. sudo bash secure_boot_setup.sh generate   → wygeneruj klucze
#   2. sudo bash secure_boot_setup.sh sign        → podpisz kernel + bootloader
#   3. sudo bash secure_boot_setup.sh enroll      → zarejestruj klucz w UEFI (wymaga restartu)
#   4. Restart → w MOK Manager wybierz "Enroll MOK" → podaj hasło z kroku 1
#   5. sudo bash secure_boot_setup.sh verify      → sprawdź status

set -euo pipefail
IFS=$'\n\t'

KEYS_DIR="/etc/robloxos/secure-boot-keys"
CERT="${KEYS_DIR}/robloxos-mok.crt"
KEY="${KEYS_DIR}/robloxos-mok.key"
DER="${KEYS_DIR}/robloxos-mok.cer"
LOG="/var/log/robloxos-secureboot.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  [OK]${NC} $*" | tee -a "$LOG"; }
info() { echo -e "${CYAN}  [..] $*${NC}" | tee -a "$LOG"; }
warn() { echo -e "${YELLOW}  [!!] $*${NC}" | tee -a "$LOG"; }
fail() { echo -e "${RED}  [✗] $*${NC}" >&2 | tee -a "$LOG"; exit 1; }

[[ $EUID -eq 0 ]] || fail "Uruchom jako root."
mkdir -p "$(dirname "$LOG")"
echo "=== Secure Boot Setup $(date) ===" >> "$LOG"

CMD="${1:-help}"

# ══════════════════════════════════════════════════════════════════════════════
generate_keys() {
# ══════════════════════════════════════════════════════════════════════════════
    info "Sprawdzam zależności..."
    for pkg in openssl sbsign mokutil efitools; do
        command -v "$pkg" &>/dev/null || {
            info "Instaluję $pkg..."
            apt-get install -y -qq "$pkg" || fail "Nie można zainstalować: $pkg"
        }
    done

    mkdir -p "$KEYS_DIR"
    chmod 700 "$KEYS_DIR"

    if [[ -f "$KEY" ]]; then
        warn "Klucze już istnieją w ${KEYS_DIR}. Usuń je ręcznie jeśli chcesz je odtworzyć."
        warn "  rm -rf ${KEYS_DIR}"
        exit 0
    fi

    info "Generuję klucz RSA 4096-bit..."
    openssl req -new -x509 \
        -newkey rsa:4096 \
        -keyout "$KEY" \
        -out "$CERT" \
        -days 3650 \
        -nodes \
        -subj "/CN=RobloxOS MOK/O=RobloxOS/C=PL/emailAddress=admin@robloxos.local" \
        2>> "$LOG"

    # Konwertuj do formatu DER (wymagany przez mokutil)
    openssl x509 -in "$CERT" -out "$DER" -outform DER
    chmod 600 "$KEY" "$CERT" "$DER"

    ok "Klucze wygenerowane:"
    echo "  Certyfikat: $CERT"
    echo "  Klucz:      $KEY"
    echo "  DER:        $DER (do importu do UEFI)"

    echo ""
    echo -e "${YELLOW}NASTĘPNY KROK:${NC}"
    echo "  sudo bash $0 sign    # podpisz kernel i bootloader"
}

# ══════════════════════════════════════════════════════════════════════════════
sign_binaries() {
# ══════════════════════════════════════════════════════════════════════════════
    [[ -f "$KEY" && -f "$CERT" ]] || fail "Brak kluczy. Uruchom najpierw: $0 generate"

    # Znajdź aktualny kernel
    KERNEL=$(ls -t /boot/vmlinuz-* | head -1)
    [[ -f "$KERNEL" ]] || fail "Nie znaleziono kernela w /boot/"

    # Znajdź bootloader GRUB EFI
    GRUB_EFI=$(find /boot/efi -name "grubx64.efi" 2>/dev/null | head -1)

    info "Podpisuję kernel: ${KERNEL}..."
    sbsign \
        --key "$KEY" \
        --cert "$CERT" \
        --output "${KERNEL}.signed" \
        "$KERNEL" 2>> "$LOG"
    mv "${KERNEL}.signed" "$KERNEL"
    ok "Kernel podpisany: $KERNEL"

    if [[ -n "$GRUB_EFI" ]]; then
        info "Podpisuję GRUB EFI: ${GRUB_EFI}..."
        sbsign \
            --key "$KEY" \
            --cert "$CERT" \
            --output "${GRUB_EFI}.signed" \
            "$GRUB_EFI" 2>> "$LOG"
        mv "${GRUB_EFI}.signed" "$GRUB_EFI"
        ok "GRUB EFI podpisany."
    else
        warn "Nie znaleziono grubx64.efi – sprawdź /boot/efi."
    fi

    # Podpisz też initramfs (opcjonalnie)
    INITRD=$(ls -t /boot/initrd.img-* | head -1)
    if [[ -f "$INITRD" ]]; then
        info "Podpisuję initramfs: ${INITRD}..."
        sbsign \
            --key "$KEY" \
            --cert "$CERT" \
            --output "${INITRD}.signed" \
            "$INITRD" 2>> "$LOG" || warn "Podpisanie initramfs nieudane (opcjonalne)."
        [[ -f "${INITRD}.signed" ]] && mv "${INITRD}.signed" "$INITRD"
    fi

    ok "Podpisywanie zakończone."
    echo ""
    echo -e "${YELLOW}NASTĘPNY KROK:${NC}"
    echo "  sudo bash $0 enroll    # zarejestruj klucz w UEFI"

    # Hook: automatyczne podpisywanie przy aktualizacji kernela (kernel-install)
    _install_signing_hook
}

# ══════════════════════════════════════════════════════════════════════════════
_install_signing_hook() {
# ══════════════════════════════════════════════════════════════════════════════
    # Zaintaluj hook który automatycznie podpisuje nowe kernele przy apt upgrade
    HOOK_FILE="/etc/kernel/postinst.d/robloxos-sign-kernel"
    cat > "$HOOK_FILE" <<HOOK
#!/bin/bash
# Auto-podpisywanie kernela po aktualizacji
set -e
KERNEL_VERSION="\$1"
KERNEL_IMG="/boot/vmlinuz-\${KERNEL_VERSION}"
if [[ -f "$KEY" && -f "$CERT" && -f "\$KERNEL_IMG" ]]; then
    sbsign --key "$KEY" --cert "$CERT" \
           --output "\${KERNEL_IMG}.signed" "\$KERNEL_IMG"
    mv "\${KERNEL_IMG}.signed" "\$KERNEL_IMG"
    echo "[RobloxOS] Kernel \${KERNEL_VERSION} podpisany."
fi
HOOK
    chmod +x "$HOOK_FILE"
    ok "Hook auto-podpisywania zainstalowany: ${HOOK_FILE}"
}

# ══════════════════════════════════════════════════════════════════════════════
enroll_key() {
# ══════════════════════════════════════════════════════════════════════════════
    [[ -f "$DER" ]] || fail "Brak pliku DER. Uruchom najpierw: $0 generate"

    info "Rejestruję klucz MOK w UEFI..."
    info "Zostaniesz poproszony o hasło – zapamiętaj je do wpisania po restarcie."
    mokutil --import "$DER"

    ok "Klucz zakolejkowany do rejestracji."
    echo ""
    echo -e "${BOLD}Po restarcie:${NC}"
    echo "  1. System uruchomi MOK Manager (niebieski ekran)"
    echo "  2. Wybierz: 'Enroll MOK'"
    echo "  3. Wybierz: 'Continue'"
    echo "  4. Wybierz: 'Yes'"
    echo "  5. Wpisz hasło które podałeś powyżej"
    echo "  6. Wybierz: 'Reboot'"
    echo ""
    echo -e "${YELLOW}Następnie sprawdź:${NC} sudo bash $0 verify"
    echo ""
    read -rp "Zrestartować teraz? [tak/nie]: " ans
    [[ "$ans" == "tak" ]] && shutdown -r now
}

# ══════════════════════════════════════════════════════════════════════════════
verify_secure_boot() {
# ══════════════════════════════════════════════════════════════════════════════
    echo ""
    echo -e "${BOLD}Status Secure Boot:${NC}"

    # Sprawdź czy Secure Boot aktywny
    if [[ -d /sys/firmware/efi ]]; then
        SB_STATUS=$(mokutil --sb-state 2>/dev/null || echo "unknown")
        if echo "$SB_STATUS" | grep -q "enabled"; then
            ok "Secure Boot: AKTYWNY"
        else
            warn "Secure Boot: ${SB_STATUS}"
        fi
    else
        warn "System nie uruchomiony w trybie UEFI (brak /sys/firmware/efi)"
    fi

    # Sprawdź podpis kernela
    KERNEL=$(ls -t /boot/vmlinuz-* | head -1)
    if sbverify --cert "$CERT" "$KERNEL" &>/dev/null; then
        ok "Kernel podpisany: $(basename "$KERNEL")"
    else
        warn "Kernel NIE jest podpisany naszym certyfikatem: $(basename "$KERNEL")"
    fi

    # Lista zarejestrowanych kluczy MOK
    echo ""
    echo "Zarejestrowane klucze MOK:"
    mokutil --list-enrolled 2>/dev/null | grep -A2 "CN=" || echo "  (brak lub błąd odczytu)"
}

# ══════════════════════════════════════════════════════════════════════════════
case "$CMD" in
    generate) generate_keys ;;
    sign)     sign_binaries ;;
    enroll)   enroll_key    ;;
    verify)   verify_secure_boot ;;
    help|*)
        echo "Użycie: $0 [generate|sign|enroll|verify]"
        echo ""
        echo "  generate  Wygeneruj klucze MOK"
        echo "  sign      Podpisz kernel i bootloader"
        echo "  enroll    Zarejestruj klucz w UEFI (wymaga restartu)"
        echo "  verify    Sprawdź status Secure Boot"
        ;;
esac
