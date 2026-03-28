#!/usr/bin/env bash
# RobloxOS – Remote Management Setup
# Konfiguruje WireGuard VPN + SSH tylko przez VPN + fail2ban.
#
# Użycie:
#   sudo bash setup_remote.sh server   → konfiguracja na konsoli gamingowej
#   sudo bash setup_remote.sh client   → generuje config dla admina (telefon/laptop)
#   sudo bash setup_remote.sh status   → status VPN i SSH
#   sudo bash setup_remote.sh disable  → wyłącz zdalne zarządzanie

set -euo pipefail
IFS=$'\n\t'

# ── Konfiguracja ──────────────────────────────────────────────────────────────
WG_IFACE="wg0"
WG_PORT=51820                  # port WireGuard (UDP)
WG_SERVER_IP="10.99.0.1/24"   # IP serwera w sieci VPN
WG_CLIENT_IP="10.99.0.2/32"   # IP klienta admina w sieci VPN
SSH_PORT=2244                  # niestandardowy port SSH (nie 22)
SSH_VPN_BIND="10.99.0.1"       # SSH nasłuchuje TYLKO na interfejsie VPN
KEYS_DIR="/etc/robloxos/wireguard"
LOG="/var/log/robloxos-setup.log"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ok()   { echo -e "${GREEN}  [OK]${NC} $*" | tee -a "$LOG"; }
info() { echo -e "${CYAN}  [..] $*${NC}" | tee -a "$LOG"; }
warn() { echo -e "${YELLOW}  [!!] $*${NC}" | tee -a "$LOG"; }
fail() { echo -e "${RED}  [✗] $*${NC}" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "Uruchom jako root."
mkdir -p "$(dirname "$LOG")" "$KEYS_DIR"
chmod 700 "$KEYS_DIR"

CMD="${1:-help}"

# ══════════════════════════════════════════════════════════════════════════════
setup_server() {
# ══════════════════════════════════════════════════════════════════════════════
    info "Instaluję zależności..."
    apt-get update -qq
    apt-get install -y -qq wireguard openssh-server fail2ban ufw

    # ── WireGuard konfiguracja ──────────────────────────────────────────────

    info "Generuję klucze WireGuard..."
    if [[ ! -f "${KEYS_DIR}/server_private.key" ]]; then
        wg genkey | tee "${KEYS_DIR}/server_private.key" | \
            wg pubkey > "${KEYS_DIR}/server_public.key"
        chmod 600 "${KEYS_DIR}/server_private.key"
    fi

    SERVER_PRIVATE=$(cat "${KEYS_DIR}/server_private.key")
    SERVER_PUBLIC=$(cat "${KEYS_DIR}/server_public.key")

    # Klucze klienta
    if [[ ! -f "${KEYS_DIR}/client_private.key" ]]; then
        wg genkey | tee "${KEYS_DIR}/client_private.key" | \
            wg pubkey > "${KEYS_DIR}/client_public.key"
        chmod 600 "${KEYS_DIR}/client_private.key"
    fi

    CLIENT_PRIVATE=$(cat "${KEYS_DIR}/client_private.key")
    CLIENT_PUBLIC=$(cat "${KEYS_DIR}/client_public.key")

    # Pobierz publiczny IP urządzenia
    PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || \
                curl -s --max-time 5 https://ifconfig.me 2>/dev/null || \
                echo "TWÓJ_PUBLICZNY_IP")

    # Konfiguracja serwera WireGuard
    cat > "/etc/wireguard/${WG_IFACE}.conf" <<EOF
# RobloxOS WireGuard Server
# Wygenerowano: $(date)

[Interface]
PrivateKey = ${SERVER_PRIVATE}
Address = ${WG_SERVER_IP}
ListenPort = ${WG_PORT}
# Zapisz zmiany konfiguracji przy zatrzymaniu
SaveConfig = false

# PostUp/PostDown: opcjonalne reguły firewall
# PostUp = iptables -A FORWARD -i ${WG_IFACE} -j ACCEPT
# PostDown = iptables -D FORWARD -i ${WG_IFACE} -j ACCEPT

[Peer]
# Admin (laptop/telefon)
PublicKey = ${CLIENT_PUBLIC}
AllowedIPs = ${WG_CLIENT_IP}
# PersistentKeepalive dla klientów za NAT
PersistentKeepalive = 25
EOF

    chmod 600 "/etc/wireguard/${WG_IFACE}.conf"

    # Włącz WireGuard
    systemctl enable --now "wg-quick@${WG_IFACE}"
    ok "WireGuard uruchomiony na porcie ${WG_PORT}/UDP."

    # ── SSH konfiguracja ────────────────────────────────────────────────────

    info "Konfiguruję SSH..."
    local sshd_conf="/etc/ssh/sshd_config.d/robloxos-remote.conf"
    cat > "$sshd_conf" <<EOF
# RobloxOS – SSH dostępny TYLKO przez VPN

# Nasłuchuj wyłącznie na interfejsie VPN
ListenAddress ${SSH_VPN_BIND}
Port ${SSH_PORT}

# Bezpieczeństwo
PermitRootLogin prohibit-password    # tylko klucze, nie hasło
PasswordAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys

# Brak X11 (nie potrzebujemy GUI przez SSH)
X11Forwarding no

# Timeout
ClientAliveInterval 300
ClientAliveCountMax 2
LoginGraceTime 30

# Tylko root przez VPN (robloxuser nie ma shellaa)
AllowUsers root
DenyUsers robloxuser

# Brak SFTP (opcjonalnie możesz włączyć)
# Subsystem sftp /usr/lib/openssh/sftp-server
EOF

    systemctl restart sshd
    ok "SSH skonfigurowany: nasłuchuje na ${SSH_VPN_BIND}:${SSH_PORT}"

    # ── Fail2ban ────────────────────────────────────────────────────────────

    info "Konfiguruję fail2ban..."
    cat > /etc/fail2ban/jail.d/robloxos-ssh.conf <<EOF
[sshd]
enabled = true
port = ${SSH_PORT}
logpath = /var/log/auth.log
maxretry = 3
findtime = 300
bantime = 3600
EOF

    systemctl enable --now fail2ban
    ok "Fail2ban aktywny (3 próby / 5 min = ban 1h)."

    # ── Wygeneruj config klienta ─────────────────────────────────────────────

    _generate_client_config "$PUBLIC_IP" "$CLIENT_PRIVATE" "$SERVER_PUBLIC"

    # ── Podsumowanie ──────────────────────────────────────────────────────────

    echo ""
    echo -e "${BOLD}${GREEN}Remote management skonfigurowany!${NC}"
    echo ""
    echo -e "  WireGuard:  ${CYAN}${PUBLIC_IP}:${WG_PORT}/UDP${NC}"
    echo -e "  SSH:        ${CYAN}${SSH_VPN_BIND}:${SSH_PORT}${NC} (przez VPN)"
    echo -e "  Server key: ${CYAN}${SERVER_PUBLIC}${NC}"
    echo ""
    echo -e "${YELLOW}Następne kroki:${NC}"
    echo "  1. Skopiuj plik klienta: ${KEYS_DIR}/client.conf"
    echo "  2. Zaimportuj do WireGuard na telefonie/laptopie"
    echo "  3. Wgraj klucz SSH admina: ssh-copy-id -p ${SSH_PORT} -i ~/.ssh/id_rsa.pub root@${SSH_VPN_BIND}"
    echo "  4. Otwórz port UDP w routerze: ${WG_PORT}"
    echo ""
    echo -e "Połączenie: ${CYAN}ssh -p ${SSH_PORT} root@10.99.0.1${NC}"
    echo -e "Web panel:  ${CYAN}https://10.99.0.1:8443${NC}"
}

# ══════════════════════════════════════════════════════════════════════════════
_generate_client_config() {
    local public_ip="$1"
    local client_private="$2"
    local server_public="$3"

    local client_conf="${KEYS_DIR}/client.conf"
    cat > "$client_conf" <<EOF
# RobloxOS – WireGuard Client Config
# Zaimportuj ten plik do aplikacji WireGuard na telefonie/laptopie
# Wygenerowano: $(date)

[Interface]
PrivateKey = ${client_private}
Address = ${WG_CLIENT_IP}
DNS = 1.1.1.1, 8.8.8.8

[Peer]
# RobloxOS Console
PublicKey = ${server_public}
Endpoint = ${public_ip}:${WG_PORT}
# AllowedIPs = 0.0.0.0/0  # cały ruch przez VPN (pełny tunel)
AllowedIPs = 10.99.0.0/24  # tylko ruch do konsoli (split tunnel – ZALECANE)
PersistentKeepalive = 25
EOF

    chmod 600 "$client_conf"
    ok "Config klienta: ${client_conf}"

    # Wygeneruj QR kod jeśli qrencode jest dostępny
    if command -v qrencode &>/dev/null; then
        echo ""
        echo -e "${CYAN}QR code dla telefonu:${NC}"
        qrencode -t ansiutf8 < "$client_conf"
    else
        info "Zainstaluj 'qrencode' aby wyświetlić QR kod: apt install qrencode"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
show_status() {
# ══════════════════════════════════════════════════════════════════════════════
    echo -e "\n${BOLD}Status Remote Management:${NC}\n"

    # WireGuard
    if systemctl is-active --quiet "wg-quick@${WG_IFACE}" 2>/dev/null; then
        ok "WireGuard: AKTYWNY"
        echo ""
        wg show "$WG_IFACE" 2>/dev/null || true
    else
        warn "WireGuard: NIEAKTYWNY"
    fi

    echo ""
    # SSH
    if systemctl is-active --quiet sshd 2>/dev/null; then
        ok "SSH: AKTYWNY na porcie ${SSH_PORT}"
        ss -tlnp | grep ":${SSH_PORT}" || true
    else
        warn "SSH: NIEAKTYWNY"
    fi

    echo ""
    # Fail2ban
    if systemctl is-active --quiet fail2ban 2>/dev/null; then
        ok "Fail2ban: AKTYWNY"
        fail2ban-client status sshd 2>/dev/null || true
    else
        warn "Fail2ban: NIEAKTYWNY"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
disable_remote() {
# ══════════════════════════════════════════════════════════════════════════════
    warn "Wyłączam zdalne zarządzanie..."
    systemctl stop "wg-quick@${WG_IFACE}"  2>/dev/null || true
    systemctl disable "wg-quick@${WG_IFACE}" 2>/dev/null || true
    rm -f "/etc/ssh/sshd_config.d/robloxos-remote.conf"
    systemctl restart sshd
    ok "Zdalne zarządzanie wyłączone."
}

# ══════════════════════════════════════════════════════════════════════════════
case "$CMD" in
    server)  setup_server  ;;
    status)  show_status   ;;
    disable) disable_remote ;;
    client)
        [[ -f "${KEYS_DIR}/client.conf" ]] || fail "Uruchom najpierw: $0 server"
        cat "${KEYS_DIR}/client.conf"
        command -v qrencode &>/dev/null && qrencode -t ansiutf8 < "${KEYS_DIR}/client.conf"
        ;;
    help|*)
        echo "Użycie: $0 [server|client|status|disable]"
        echo ""
        echo "  server   Skonfiguruj WireGuard + SSH + fail2ban na konsoli"
        echo "  client   Wyświetl config klienta (do importu na telefon)"
        echo "  status   Sprawdź status"
        echo "  disable  Wyłącz zdalne zarządzanie"
        ;;
esac
