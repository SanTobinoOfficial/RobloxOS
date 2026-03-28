# Instrukcja wdrożenia RobloxOS Web Panel

> Pełny przewodnik krok po kroku.
> Poziom: **dla osoby nietech** – każdy krok jest wyjaśniony dokładnie.

---

## Co osiągniemy

```
[Telefon rodzica] ──HTTPS──► [Panel Replit] ◄──co 30s── [Maszyna RobloxOS]
                                    ↓
                           Widać na żywo:
                           • Czy Roblox jest włączony
                           • Ile czasu zostało
                           • Czy limity działają
```

Cały proces zajmuje **około 15 minut**.

---

# KROK A – Wdrożenie panelu na Replit

Replit to darmowa strona, która uruchomi nasz panel w chmurze.
Nie trzeba kupować serwera ani konfigurować żadnych portów.

## A1 – Założenie konta na Replit

1. Wejdź na **[replit.com](https://replit.com)**
2. Kliknij **Sign Up** (Zarejestruj się)
3. Wybierz **Continue with Google** – zaloguj się kontem Google
4. Zakończ rejestrację

> Konto Replit jest **bezpłatne**. Nie podajesz karty kredytowej.

---

## A2 – Import projektu

1. Po zalogowaniu kliknij **+ Create Repl** (niebieski przycisk)

2. Wybierz zakładkę **Import from GitHub**

3. W polu URL wklej:
   ```
   https://github.com/SanTobinoOfficial/RobloxOS
   ```

4. Kliknij **Import from GitHub**

5. Poczekaj chwilę – Replit pobiera pliki projektu

6. Po zakończeniu importu zmień komendę uruchomienia:
   - Znajdź pole **Run command** (może być już wypełnione)
   - Ustaw na:
     ```
     python3 webpanel/app.py
     ```

7. Kliknij **Run** (zielony przycisk ▶)

**Co zobaczysz w konsoli:**
```
PIERWSZE URUCHOMIENIE: konto admin/admin123 utworzone.
RobloxOS Web Panel (Replit Edition) – http://0.0.0.0:8080
```

> Jeśli widzisz błędy o brakujących pakietach, poczekaj – Replit
> instaluje je automatycznie przy pierwszym uruchomieniu.

---

## A3 – Pierwsze logowanie i zmiana hasła

1. Kliknij przycisk **Open in new tab** (ikona strzałki w górnym prawym rogu)
   - Otworzy się panel w nowej karcie przeglądarki

2. Zostaniesz przekierowany na stronę logowania:

   ```
   Hasło administratora: [ admin123 ]
                         [ Zaloguj się ]
   ```

3. Wpisz hasło **`admin123`** i kliknij **Zaloguj się**

4. Zostaniesz **automatycznie przeniesiony** na stronę zmiany hasła
   (to jednorazowe zabezpieczenie przy pierwszym uruchomieniu)

5. Wypełnij formularz:
   - **Obecne hasło:** `admin123`
   - **Nowe hasło:** (wymyśl własne, min. 8 znaków)
   - **Powtórz nowe hasło:** (to samo jeszcze raz)

6. Kliknij **Zmień hasło**

> **Zapamiętaj nowe hasło!** Jeśli je zapomnisz, możesz je zresetować
> ze skryptu – patrz sekcja Rozwiązywanie problemów na końcu.

---

## A4 – Skopiowanie tokenu API

Token API to hasło dla maszyny RobloxOS, żeby mogła wysyłać dane do panelu.

1. W panelu kliknij przycisk:
   ```
   🔑 Pokaż token API (podłącz maszynę)
   ```
   (widoczny na dashboardzie w sekcji "Szybkie akcje")

2. Otworzy się strona z JSON:
   ```json
   {
     "api_token": "a3f8c2d1e9b7...",
     "endpoint": "https://robloxos.twojanazwa.repl.co/api/update"
   }
   ```

3. **Skopiuj i zapisz w bezpiecznym miejscu:**
   - wartość `api_token` (długi ciąg liter i cyfr)
   - wartość `endpoint` (adres URL)

> Zapisz je np. w Notatniku lub prześlij sobie e-mailem.
> Będą potrzebne w Kroku B.

**Panel jest teraz gotowy!** Działa w trybie DEMO (złoty baner u góry).
W Kroku B połączymy go z maszyną RobloxOS.

---

# KROK B – Połączenie maszyny RobloxOS z panelem

Teraz skonfigurujemy maszynę, żeby co 30 sekund wysyłała dane do panelu.

## B1 – Uruchomienie skryptu instalacyjnego

1. Na maszynie RobloxOS otwórz terminal

2. Wpisz komendę:
   ```bash
   sudo bash remote/setup_replit_sync.sh
   ```

3. Skrypt zapyta o kilka rzeczy – odpowiedz na każde pytanie:

---

## B2 – Odpowiedzi na pytania skryptu

```
============================================
  RobloxOS → Replit Sync – Konfiguracja
============================================

[?] Podaj URL panelu Replit:
    (np. https://robloxos-panel.twojanazwa.repl.co)
>
```
➜ Wklej endpoint URL skopiowany w Kroku A4 (bez `/api/update` na końcu).
   Przykład: `https://robloxos-panel.twojanazwa.repl.co`

---

```
[?] Podaj token API (z dashboardu panelu):
>
```
➜ Wklej wartość `api_token` skopiowaną w Kroku A4.

---

```
[✓] Testuję połączenie z panelem...
[✓] Połączenie OK – panel odpowiada.
[✓] Token API zweryfikowany.
[✓] Usługa sync.service zainstalowana i uruchomiona.

============================================
  Konfiguracja zakończona pomyślnie!
============================================

Panel URL: https://robloxos-panel.twojanazwa.repl.co
Status sync: aktywny (co 30 sekund)
Log: /var/log/robloxos-sync.log
```

## B3 – Sprawdzenie w panelu

1. Odśwież stronę panelu na telefonie lub komputerze

2. Złoty baner **TRYB DEMO** powinien zniknąć

3. W górze powinna pojawić się **zielona belka**:
   ```
   ● POŁĄCZONO Z MASZYNĄ ROBLOXOS – dane na żywo
   ```

4. Jeśli Roblox jest aktualnie włączony na maszynie, zobaczysz:
   - 🎮 Roblox **aktywny** w górnym prawym rogu
   - Aktualny czas sesji (rośnie co 30 sekund)

---

# KROK C – Testowanie na telefonie

## C1 – Otwórz panel na telefonie

1. Wejdź na adres panelu: `https://robloxos-panel.twojanazwa.repl.co`
2. Zaloguj się swoim hasłem
3. Panel jest responsywny – działa na każdym telefonie

## C2 – Test: zmiana whitelisty

1. Kliknij **Whitelist** w menu po lewej
2. Dodaj domenę testową, np. `wikipedia.org`
3. Powinna pojawić się na liście
4. Usuń ją – powinna zniknąć
5. Zmiany są zapisywane natychmiast ✓

## C3 – Test: zmiana limitu czasu

1. Kliknij **Limity czasu** w menu
2. Przesuń suwak Roblox np. na `90 minut`
3. Kliknij **Zapisz ustawienia**
4. Wróć na Dashboard – limit powinien być widoczny ✓

## C4 – Test: live dane

1. Na maszynie RobloxOS włącz Roblox
2. Poczekaj maksymalnie 30 sekund
3. W panelu powinien pojawić się 🎮 **Roblox aktywny** ✓
4. Czas sesji powinien rosnąć co 30 sekund ✓

---

# Codzienne użytkowanie

## Jak sprawdzić czy Roblox jest włączony

1. Wejdź na adres panelu
2. Zaloguj się
3. W górnym prawym rogu zobaczysz status aplikacji

## Jak zmienić limit czasu

1. Menu → **Limity czasu**
2. Przesuń suwak
3. **Zapisz** → zmiana wchodzi w życie natychmiast

## Jak zablokować stronę

1. Menu → **Whitelist**
2. Znajdź domenę i kliknij **Usuń**
3. Od tej chwili strona jest niedostępna na maszynie

## Jak dodać nową dozwoloną stronę

1. Menu → **Whitelist**
2. Wpisz domenę (np. `khanacademy.org`)
3. Kliknij **Dodaj domenę**

---

# Rozwiązywanie problemów

## Panel nie otwiera się / "This site can't be reached"

**Przyczyna:** Replit zatrzymał serwer (darmowe konta mają limit czasu bezczynności).

**Rozwiązanie:**
1. Wejdź na [replit.com](https://replit.com)
2. Znajdź swój projekt (RobloxOS)
3. Kliknij **Run**
4. Poczekaj 30 sekund i odśwież panel

> Aby panel działał bez przerwy – rozważ upgrade Replit do planu **Hacker** ($7/miesiąc)
> lub użyj metody z UptimeRobot opisanej poniżej.

## Panel ciągle się wyłącza

Darmowy Replit usypia serwery po 5 minutach braku ruchu.

**Rozwiązanie – UptimeRobot (darmowe):**
1. Wejdź na [uptimerobot.com](https://uptimerobot.com) i załóż konto
2. Kliknij **Add New Monitor**
3. Wybierz typ: **HTTP(s)**
4. URL: `https://twoj-panel.replit.app/login`
5. Interval: **5 minutes**
6. Kliknij **Create Monitor**

UptimeRobot będzie odwiedzać panel co 5 minut – Replit nie uśpi serwera.

## Zielona belka nie pojawia się (brak danych LIVE)

**Krok 1** – Sprawdź status usługi na maszynie:
```bash
sudo systemctl status robloxos-sync
```
Powinno pokazać `active (running)`.

**Krok 2** – Jeśli usługa nie działa:
```bash
sudo systemctl start robloxos-sync
sudo systemctl enable robloxos-sync
```

**Krok 3** – Sprawdź logi:
```bash
sudo tail -50 /var/log/robloxos-sync.log
```
Szukaj linii `[ERROR]` – powiedzą co jest nie tak.

**Krok 4** – Sprawdź czy maszyna ma internet:
```bash
curl -I https://twoj-panel.replit.app
```
Powinno odpowiedzieć kodem `200` lub `302`.

## Zapomniałem hasła do panelu

Na maszynie RobloxOS lub w Shell na Replit:
```bash
python3 -c "
import json, bcrypt, pathlib
path = pathlib.Path('webpanel/data/config.json')
cfg  = json.loads(path.read_text())
nowe = input('Nowe haslo: ').encode()
cfg['admin_password_hash']   = bcrypt.hashpw(nowe, bcrypt.gensalt(12)).decode()
cfg['force_password_change'] = True
path.write_text(json.dumps(cfg, indent=2))
print('Haslo zresetowane!')
"
```

## "Unauthorized" w logach synca

Token API jest nieprawidłowy. Uruchom ponownie setup:
```bash
sudo bash remote/setup_replit_sync.sh
```
i wklej aktualny token z panelu (`/api/token`).

---

# Alternatywa: Docker (jeśli Replit nie działa)

Jeśli wolisz uruchomić panel lokalnie lub na własnym serwerze:

## Wymagania
- Serwer lub VPS z Ubuntu 22.04
- Zainstalowany Docker: `sudo apt install docker.io`
- Domena lub dostęp przez IP

## Uruchomienie

```bash
# Wejdź do folderu projektu
cd /sciezka/do/RobloxOS

# Zbuduj obraz
docker build -f webpanel/Dockerfile -t robloxos-panel webpanel/

# Uruchom (port 8080)
docker run -d \
  --name robloxos-panel \
  -p 8080:8080 \
  -v $(pwd)/webpanel/data:/app/data \
  --restart unless-stopped \
  robloxos-panel

# Sprawdź czy działa
docker ps
docker logs robloxos-panel
```

Panel będzie dostępny na `http://IP_SERWERA:8080`.

Aby był dostępny przez HTTPS (wymagane dla telefonu rodzica z nowszym Androidem/iOS),
skonfiguruj Nginx jako reverse proxy lub użyj Cloudflare Tunnel.

---

# Podsumowanie – lista kontrolna

```
[ ] Konto Replit założone
[ ] Projekt zaimportowany z GitHub
[ ] Panel uruchomiony (Run ▶)
[ ] Hasło admin123 zmienione
[ ] Token API skopiowany
[ ] setup_replit_sync.sh uruchomiony na maszynie RobloxOS
[ ] Zielona belka LIVE widoczna w panelu
[ ] Test whitelist – działa
[ ] Test limitu czasu – działa
[ ] Panel działa na telefonie rodzica
```

Jeśli wszystkie punkty są zaznaczone – instalacja zakończona pomyślnie! 🎉
