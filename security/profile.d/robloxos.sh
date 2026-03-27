#!/bin/bash
# /etc/profile.d/robloxos.sh
# RobloxOS – ograniczenia środowiska dla użytkownika robloxuser.
#
# Ten plik jest sourcowany przez każdy login shell (/bin/bash, /bin/sh itp.)
# dla WSZYSTKICH użytkowników, ale aktywne ograniczenia dotyczą TYLKO
# użytkownika robloxuser.
#
# UWAGA: To jest linia obrony dla scenariusza gdy ktoś mimo wszystko
# dostanie się do shella. Główna blokada to shell=/usr/sbin/nologin
# ustawiony przez install_security.sh.

# Jeśli to nie jest robloxuser – nie rób nic
if [ "$(id -un)" != "robloxuser" ]; then
    return 0
fi

# ── 1. Natychmiastowe wyjście z shella ───────────────────────────────────────
# Jeśli shell jest interaktywny (np. ktoś otworzył terminal przez lukę),
# wychodzimy od razu z kodem 1. Logujemy próbę.
if [ -t 0 ]; then
    logger -t robloxos-security \
        "ALERT: robloxuser próbował otworzyć interaktywny shell ($(tty)) – zablokowano"
    echo "Brak dostępu do powłoki systemowej." >&2
    exit 1
fi

# ── 2. Środowisko – tylko to co potrzebne ────────────────────────────────────
# Ograniczamy PATH do absolutnego minimum; żadnych użytkowych narzędzi.
export PATH="/usr/bin:/bin"

# Wyłącz history całkowicie
export HISTFILE=/dev/null
export HISTSIZE=0
export HISTFILESIZE=0
unset  HISTFILE

# Brak edytora, brak pagera – na wypadek gdyby coś próbowało je otworzyć
export EDITOR=/bin/false
export VISUAL=/bin/false
export PAGER=/bin/false
export BROWSER=/bin/false

# ── 3. Aliasy blokujące destrukcyjne komendy ─────────────────────────────────
# alias działa tylko w bash; dla sh-compatible shellów używamy funkcji.
alias rm='echo "Operacja zablokowana." && false'
alias mv='echo "Operacja zablokowana." && false'
alias cp='echo "Operacja zablokowana." && false'
alias chmod='echo "Operacja zablokowana." && false'
alias chown='echo "Operacja zablokowana." && false'
alias wget='echo "Operacja zablokowana." && false'
alias curl='echo "Operacja zablokowana." && false'
alias sudo='echo "Operacja zablokowana." && false'
alias su='echo "Operacja zablokowana." && false'
alias apt='echo "Operacja zablokowana." && false'
alias apt-get='echo "Operacja zablokowana." && false'
alias dpkg='echo "Operacja zablokowana." && false'
alias snap='echo "Operacja zablokowana." && false'
alias flatpak='echo "Operacja zablokowana." && false'

# Blokada uruchamiania innych powłok z poziomu tej powłoki
alias bash='echo "Operacja zablokowana." && false'
alias sh='echo "Operacja zablokowana." && false'
alias zsh='echo "Operacja zablokowana." && false'
alias python3='echo "Operacja zablokowana." && false'
alias python='echo "Operacja zablokowana." && false'

# ── 4. Zablokuj możliwość modyfikacji aliasów ─────────────────────────────────
# Użytkownik nie może unalias ani nadpisać funkcji przez własny .bashrc
readonly -f command_not_found_handle 2>/dev/null || true

# ── 5. Loguj każdą próbę uruchomienia shella ─────────────────────────────────
logger -t robloxos-security \
    "INFO: robloxuser sourcował profile.d/robloxos.sh (shell: $0, PID: $$)"
