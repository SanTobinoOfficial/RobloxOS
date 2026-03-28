# RobloxOS Web Panel – Replit Edition

Panel administracyjny dla projektu RobloxOS dostosowany do wdrożenia na Replit.
Działa w **trybie demo** (dane symulowane) lub połączony z prawdziwą maszyną RobloxOS.

---

## Szybki start na Replit

### 1. Importuj projekt

1. Zaloguj się na [replit.com](https://replit.com)
2. Kliknij **+ Create Repl** → **Import from GitHub**
3. Podaj URL swojego repozytorium
4. Replit wykryje `.replit` i ustawi konfigurację automatycznie

Alternatywnie: **Upload folder** i wgraj zawartość katalogu `webpanel/`.

### 2. Kliknij Run

Replit zainstaluje zależności z `requirements.txt` i uruchomi panel.
W konsoli zobaczysz:

```
PIERWSZE URUCHOMIENIE: konto admin/admin123 utworzone.
RobloxOS Web Panel (Replit Edition) – http://0.0.0.0:8080
```

### 3. Zmień hasło

1. Otwórz panel (przycisk **Open in new tab** w Replit)
2. Zaloguj się hasłem **`admin123`**
3. Zostaniesz przekierowany na stronę zmiany hasła – **ustaw własne hasło**

Panel jest teraz publiczny pod adresem `https://<twoj-repl>.replit.app`.

---

## Tryby pracy

### Tryb DEMO (domyślny)

Gdy nie ma połączenia z maszyną, panel pokazuje **symulowane dane**:

| Dane | Wartość |
|------|---------|
| Aktywna aplikacja | Roblox |
| Czas sesji | ~1h 23min (rośnie) |
| FPS | 45–62 (losowe) |
| Ping | 18–65 ms (losowe) |
| Status usług | wszystkie `active` |
| Logi | generowane co 2–4s |

Złoty banner **TRYB DEMO** informuje, że dane są symulowane.

Whitelist i limity czasu **zapisują się naprawdę** do `data/config.json`
i będą aktywne po podłączeniu prawdziwej maszyny.

### Tryb LIVE (połączona maszyna)

Gdy maszyna RobloxOS wysyła dane, pojawia się zielony banner
**POŁĄCZONO Z MASZYNĄ ROBLOXOS**. Dane są aktualne (odświeżane co ~30s).

---

## Połączenie z prawdziwą maszyną RobloxOS

### Krok 1 – Pobierz token API

Po zalogowaniu do panelu odwiedź:
```
https://<twoj-repl>.replit.app/api/token
```
Zobaczysz JSON z tokenem i endpointem, np.:
```json
{
  "api_token": "a3f8c2...",
  "endpoint": "https://robloxos-panel.replit.app/api/update",
  "header": "X-RobloxOS-Token"
}
```

### Krok 2 – Skonfiguruj maszynę RobloxOS

Na maszynie RobloxOS (Raspberry Pi / mini-PC) utwórz skrypt
`/home/robloxuser/launcher/panel_push.py`:

```python
#!/usr/bin/env python3
"""Wysyła dane do panelu Replit co 30 sekund."""

import time
import requests
import psutil
import subprocess

PANEL_URL = "https://<twoj-repl>.replit.app/api/update"
TOKEN     = "a3f8c2..."  # skopiuj z /api/token

def get_active_app():
    for proc in psutil.process_iter(["name"]):
        name = proc.info["name"].lower()
        if "sober" in name or "roblox" in name:
            return "roblox"
        if "discord" in name:
            return "discord"
        if "chromium" in name:
            return "browser"
    return ""

def get_session_time(app):
    try:
        import json
        state = json.loads(open("/var/lib/robloxos/session_times.json").read())
        return state.get(app, 0)
    except Exception:
        return 0

while True:
    try:
        app = get_active_app()
        mem = psutil.virtual_memory()
        data = {
            "active_app":   app,
            "session_time": get_session_time(app),
            "ram_mb":       mem.used // (1024 ** 2),
            "fps":          0,   # uzupełnij jeśli masz źródło FPS
            "ping":         0,   # uzupełnij jeśli masz źródło pingu
        }
        requests.post(PANEL_URL, json=data,
                      headers={"X-RobloxOS-Token": TOKEN}, timeout=10)
    except Exception as e:
        print(f"Błąd push: {e}")
    time.sleep(30)
```

Dodaj do `crontab` lub `systemd`, żeby startował automatycznie:
```bash
# crontab -e
@reboot python3 /home/robloxuser/launcher/panel_push.py &
```

### Krok 3 – Sprawdź połączenie

W panelu Replit powinien pojawić się zielony banner **POŁĄCZONO Z MASZYNĄ**.

---

## Zmiana mock data na własne wartości

Edytuj `mock_data.py`:

```python
# Zmień bazowy czas sesji (sekundy)
self._base_session = {"roblox": 4980, "discord": 1200, "browser": 600}

# Zmień zakres FPS i pingu
self._fps_val  = 58   # startowy FPS
self._ping_val = 32   # startowy ping

# Dodaj własne szablony logów
_LOG_TEMPLATES = [
    "[INFO]  Własny log: ...",
    ...
]
```

---

## Zmienne środowiskowe (Replit Secrets)

W Replit przejdź do **Secrets** (kłódka w bocznym menu) i dodaj:

| Zmienna | Opis | Przykład |
|---------|------|---------|
| `SECRET_KEY` | Klucz sesji Flask (opcjonalne – generowany automatycznie) | `losowy-ciag-32-znakow` |
| `REPLIT_MODE` | Wymuś tryb demo nawet bez REPL_ID | `true` |

---

## Struktura plików

```
webpanel/
├── app.py              ← główna aplikacja Flask (Replit Edition)
├── mock_data.py        ← generator symulowanych danych
├── requirements.txt    ← flask, bcrypt, psutil, flask-socketio
├── .replit             ← konfiguracja uruchomienia Replit
├── replit.nix          ← zależności systemowe (Python 3.11)
├── data/               ← dane runtime (tworzony automatycznie)
│   ├── config.json     ← hasło hash + whitelist + limity (auto)
│   └── logs/           ← logi (puste w demo)
└── templates/
    ├── base.html       ← layout + banner DEMO/LIVE
    ├── login.html      ← logowanie + info o pierwszym uruchomieniu
    ├── dashboard.html  ← statystyki + FPS/ping
    ├── whitelist.html  ← zarządzanie whitelistą (działa naprawdę)
    ├── timelimits.html ← limity czasu (działa naprawdę)
    ├── logs.html       ← live tail logów (mock w demo)
    └── change_password.html ← zmiana hasła
```

---

## API Reference

### `POST /api/update`
Przyjmuje dane z maszyny RobloxOS.

**Nagłówek:** `X-RobloxOS-Token: <token>`

**Body JSON:**
```json
{
  "session_time": 5400,
  "active_app":   "roblox",
  "fps":          45,
  "ping":         32,
  "ram_mb":       1240
}
```

**Odpowiedź:**
```json
{ "ok": true, "received_at": "2024-01-15T14:32:00" }
```

Dane są ważne przez **90 sekund**. Po tym czasie panel wraca do trybu demo.

### `GET /api/token`
Zwraca token API i endpoint (wymaga zalogowania).

### `GET /api/status`
Zwraca pełny status systemu (mock lub realne dane).

### `POST /api/session/reset`
Resetuje licznik sesji dla aplikacji (`{"app": "roblox"}`).

---

## FAQ

**Panel nie startuje** → Sprawdź czy `requirements.txt` zainstalował się poprawnie.
Kliknij Shell w Replit i uruchom ręcznie: `pip install -r requirements.txt`

**Zapomniałem hasła** → W Shell Replit:
```bash
python3 -c "
import json, bcrypt
cfg = json.load(open('data/config.json'))
cfg['admin_password_hash'] = bcrypt.hashpw(b'nowe_haslo', bcrypt.gensalt(12)).decode()
cfg['force_password_change'] = True
json.dump(cfg, open('data/config.json','w'), indent=2)
print('Hasło zresetowane do: nowe_haslo')
"
```

**Dane z maszyny nie docierają** → Sprawdź:
1. Token w `panel_push.py` zgadza się z `/api/token`
2. URL endpointu jest poprawny (kończy się na `/api/update`)
3. Maszyna ma dostęp do internetu: `curl -I https://<twoj-repl>.replit.app`
