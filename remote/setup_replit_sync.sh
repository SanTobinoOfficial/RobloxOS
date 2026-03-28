#!/usr/bin/env bash
# =============================================================================
# RobloxOS – Konfiguracja synchronizacji z panelem Replit
# Uruchomienie: sudo bash remote/setup_replit_sync.sh
# Ubuntu 22.04 / Debian 12
# =============================================================================

set -euo pipefail

# ── Kolory ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "${GREEN}[✓]${RESET} $*"; }
info() { echo -e "${BLUE}[i]${RESET} $*"; }
warn() { echo -e "${YELLOW}[!]${RESET} $*"; }
err()  { echo -e "${RED}[✗]${RESET} $*" >&2; }
die()  { err "$*"; exit 1; }

# ── Stałe ────────────────────────────────────────────────────────────────────
CONFIG_FILE="/etc/robloxos/config.json"
SERVICE_FILE="/etc/systemd/system/robloxos-sync.service"
SYNC_SCRIPT="/home/robloxuser/launcher/sync_to_replit.py"
LOG_FILE="/var/log/robloxos-sync.log"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Sprawdź uprawnienia ───────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && die "Ten skrypt wymaga uprawnień root. Użyj: sudo bash $0"

# ── Baner ────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}============================================${RESET}"
echo -e "${BOLD}  RobloxOS → Replit Sync – Konfiguracja   ${RESET}"
echo -e "${BOLD}============================================${RESET}"
echo ""

# ── Sprawdź zależności ────────────────────────────────────────────────────────
info "Sprawdzam zależności..."

if ! command -v python3 &>/dev/null; then
    die "Python3 nie jest zainstalowany. Uruchom: sudo apt install python3"
fi

PYTHON=$(command -v python3)

# Sprawdź pip packages
for pkg in requests psutil; do
    if ! "$PYTHON" -c "import $pkg" 2>/dev/null; then
        info "Instaluję pakiet $pkg..."
        "$PYTHON" -m pip install --quiet "$pkg" || \
            die "Nie można zainstalować $pkg. Uruchom: pip3 install $pkg"
    fi
done
ok "Zależności OK"

# ── Wczytaj istniejącą konfigurację ──────────────────────────────────────────
CURRENT_URL=""
CURRENT_TOKEN=""

if [[ -f "$CONFIG_FILE" ]]; then
    CURRENT_URL=$(   "$PYTHON" -c "import json,sys; c=json.load(open('$CONFIG_FILE')); print(c.get('replit_url',''))"   2>/dev/null || true)
    CURRENT_TOKEN=$( "$PYTHON" -c "import json,sys; c=json.load(open('$CONFIG_FILE')); print(c.get('replit_token',''))" 2>/dev/null || true)
fi

# ── Pytanie o URL ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[?] Podaj URL panelu Replit${RESET}"
echo "    Format: https://robloxos-panel.TWOJA_NAZWA.repl.co"
if [[ -n "$CURRENT_URL" ]]; then
    echo -e "    Aktualny: ${YELLOW}${CURRENT_URL}${RESET} (Enter = zachowaj)"
fi
echo -n "> "
read -r INPUT_URL

if [[ -n "$INPUT_URL" ]]; then
    REPLIT_URL="${INPUT_URL%/}"   # usuń trailing slash
elif [[ -n "$CURRENT_URL" ]]; then
    REPLIT_URL="$CURRENT_URL"
else
    die "URL jest wymagany."
fi

# Walidacja URL
if [[ ! "$REPLIT_URL" =~ ^https?:// ]]; then
    die "Nieprawidłowy URL – musi zaczynać się od https://"
fi

# ── Pytanie o token ───────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}[?] Podaj token API${RESET}"
echo "    Znajdziesz go w panelu: Dashboard → 🔑 Pokaż token API"
echo "    Lub otwórz: ${REPLIT_URL}/api/token (musisz być zalogowany)"
if [[ -n "$CURRENT_TOKEN" ]]; then
    MASKED="${CURRENT_TOKEN:0:8}...${CURRENT_TOKEN: -4}"
    echo -e "    Aktualny: ${YELLOW}${MASKED}${RESET} (Enter = zachowaj)"
fi
echo -n "> "
read -r -s INPUT_TOKEN   # -s = nie pokazuj na ekranie
echo ""

if [[ -n "$INPUT_TOKEN" ]]; then
    REPLIT_TOKEN="$INPUT_TOKEN"
elif [[ -n "$CURRENT_TOKEN" ]]; then
    REPLIT_TOKEN="$CURRENT_TOKEN"
else
    die "Token API jest wymagany."
fi

if [[ ${#REPLIT_TOKEN} -lt 16 ]]; then
    die "Token jest zbyt krótki (min. 16 znaków). Sprawdź czy skopiowałeś całość."
fi

# ── Test połączenia ───────────────────────────────────────────────────────────
echo ""
info "Testuję połączenie z panelem..."

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 10 \
    "${REPLIT_URL}/login" 2>/dev/null || echo "000")

if [[ "$HTTP_CODE" == "000" ]]; then
    die "Brak połączenia z ${REPLIT_URL}. Sprawdź URL i czy panel działa na Replit."
elif [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "302" ]]; then
    warn "Panel zwrócił kod $HTTP_CODE (oczekiwano 200/302). Kontynuuję..."
else
    ok "Panel odpowiada (HTTP $HTTP_CODE)"
fi

# ── Test tokenu ───────────────────────────────────────────────────────────────
info "Weryfikuję token API..."

TEST_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    --max-time 10 \
    -X POST "${REPLIT_URL}/api/update" \
    -H "X-RobloxOS-Token: ${REPLIT_TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"active_app":"test","session_time":0,"fps":0,"ping":0,"ram_mb":0}' \
    2>/dev/null || echo "000")

case "$TEST_RESPONSE" in
    200) ok "Token API zweryfikowany – połączenie działa!" ;;
    401) die "Token nieprawidłowy (401). Skopiuj token ponownie z panelu: ${REPLIT_URL}/api/token" ;;
    000) die "Brak odpowiedzi od panelu. Sprawdź URL." ;;
    *)   warn "Odpowiedź: HTTP $TEST_RESPONSE (może być OK jeśli panel dopiero startuje)" ;;
esac

# ── Zapis do config.json ──────────────────────────────────────────────────────
echo ""
info "Zapisuję konfigurację do ${CONFIG_FILE}..."

mkdir -p "$(dirname "$CONFIG_FILE")"

# Aktualizuj config.json (zachowaj istniejące pola)
"$PYTHON" - <<PYEOF
import json, pathlib, sys

path = pathlib.Path("$CONFIG_FILE")
try:
    cfg = json.loads(path.read_text()) if path.exists() else {}
except Exception:
    cfg = {}

cfg["replit_url"]   = "$REPLIT_URL"
cfg["replit_token"] = "$REPLIT_TOKEN"

path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
print(f"  Zapisano: {path}")
PYEOF

chmod 640 "$CONFIG_FILE"
ok "Konfiguracja zapisana"

# ── Kopiuj skrypt sync ────────────────────────────────────────────────────────
echo ""
info "Instaluję skrypt sync..."

SYNC_SOURCE="${SCRIPT_DIR}/sync_to_replit.py"
if [[ ! -f "$SYNC_SOURCE" ]]; then
    die "Nie znaleziono ${SYNC_SOURCE}. Uruchom skrypt z katalogu projektu RobloxOS."
fi

mkdir -p "$(dirname "$SYNC_SCRIPT")"
cp "$SYNC_SOURCE" "$SYNC_SCRIPT"
chmod 755 "$SYNC_SCRIPT"
ok "Skrypt zainstalowany: ${SYNC_SCRIPT}"

# ── Utwórz log file ───────────────────────────────────────────────────────────
touch "$LOG_FILE"
chmod 664 "$LOG_FILE"

# ── Utwórz plik systemd service ───────────────────────────────────────────────
echo ""
info "Tworzę usługę systemd: robloxos-sync..."

cat > "$SERVICE_FILE" <<SERVICEEOF
[Unit]
Description=RobloxOS – sync danych do panelu Replit
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=120
StartLimitBurst=5

[Service]
Type=simple
User=root
ExecStart=${PYTHON} ${SYNC_SCRIPT}
Restart=on-failure
RestartSec=15s
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}
Environment=PYTHONUNBUFFERED=1

# Łagodne limity – nie ubijaj przy chwilowych błędach
TimeoutStartSec=30
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
SERVICEEOF

ok "Plik service zapisany: ${SERVICE_FILE}"

# ── Włącz i uruchom usługę ────────────────────────────────────────────────────
echo ""
info "Włączam i uruchamiam usługę..."

systemctl daemon-reload
systemctl enable  robloxos-sync --quiet
systemctl restart robloxos-sync

# Poczekaj chwilę i sprawdź status
sleep 3

if systemctl is-active --quiet robloxos-sync; then
    ok "Usługa robloxos-sync działa poprawnie"
else
    err "Usługa nie uruchomiła się. Sprawdź logi:"
    echo ""
    journalctl -u robloxos-sync --no-pager -n 20
    exit 1
fi

# ── Podsumowanie ──────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}============================================${RESET}"
echo -e "${BOLD}${GREEN}  Konfiguracja zakończona pomyślnie!       ${RESET}"
echo -e "${BOLD}${GREEN}============================================${RESET}"
echo ""
echo -e "  Panel URL:    ${BLUE}${REPLIT_URL}${RESET}"
echo -e "  Interval:     co 30 sekund"
echo -e "  Log:          ${LOG_FILE}"
echo -e "  Status:       $(systemctl is-active robloxos-sync)"
echo ""
echo -e "  Przydatne komendy:"
echo -e "  ${YELLOW}sudo systemctl status robloxos-sync${RESET}    # sprawdź status"
echo -e "  ${YELLOW}sudo tail -f ${LOG_FILE}${RESET}  # obserwuj logi na żywo"
echo -e "  ${YELLOW}sudo systemctl restart robloxos-sync${RESET}   # restart"
echo ""
echo -e "  Odśwież panel Replit – powinna pojawić się"
echo -e "  ${GREEN}zielona belka 'POŁĄCZONO Z MASZYNĄ ROBLOXOS'${RESET}"
echo ""
