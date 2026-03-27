# RobloxOS – Instrukcja budowania ISO przez Cubic

Cubic (Custom Ubuntu ISO Creator) to narzędzie GUI które pozwala
zmodyfikować Ubuntu ISO i spakować je z powrotem do pliku `.iso`.

---

## Wymagania przed startem

| Co | Skąd |
|----|------|
| Ubuntu 22.04 LTS (maszyna buildowa) | własna instalacja |
| Cubic ≥ 2022.01 | PPA: `ppa:cubic-wizard/release` |
| Ubuntu 22.04 Desktop ISO | releases.ubuntu.com/22.04/ |
| ~20 GB wolnego miejsca | katalog projektu |
| Internet | Flatpak Discord + Sober podczas chroot |

### Instalacja Cubic

```bash
sudo apt-add-repository ppa:cubic-wizard/release
sudo apt-get update
sudo apt-get install cubic
```

---

## Krok 1 – Przygotuj pliki projektu

Upewnij się że masz pełną strukturę projektu RobloxOS:

```
robloxos/
├── launcher/
├── openbox/
├── browser/
├── security/
└── iso/
    ├── chroot-setup.sh
    ├── lightdm/
    └── preseed/
```

Lub użyj `make iso` który zrobi to automatycznie:

```bash
cd iso/
make deps
make iso
```

---

## Krok 2 – Uruchom Cubic

```bash
cubic
# lub
sudo cubic   # jeśli potrzebujesz uprawnień
```

W oknie Cubic:

1. **Project directory** → wybierz lub utwórz pusty katalog, np. `/home/user/robloxos-build`
2. **Original ISO** → wskaż pobrany `ubuntu-22.04.4-desktop-amd64.iso`
3. Kliknij **Next**

---

## Krok 3 – Parametry ISO

W następnym ekranie Cubic uzupełnij:

| Pole | Wartość |
|------|---------|
| Custom ISO file name | `robloxos-1.0-amd64` |
| Volume ID | `RobloxOS 1.0` |
| Disk name | `RobloxOS Gaming Console` |
| Release | `1.0` |

Kliknij **Next** – Cubic wypakuje ISO i otworzy terminal chroot.

---

## Krok 4 – Terminal Cubic (chroot)

Jesteś teraz wewnątrz systemu. Wykonaj kolejno:

### 4a. Skopiuj pliki projektu do chroot

W osobnym oknie terminala na maszynie buildowej:

```bash
# Skopiuj pliki projektu do katalogu Cubic
# (Cubic montuje /cdrom jako katalog projektu)
sudo cp -r /ścieżka/do/robloxos/ /home/user/robloxos-build/
```

W terminalu Cubic (wewnątrz chroot):

```bash
# Sprawdź czy pliki są widoczne
ls /cdrom/robloxos/

# Skopiuj do /tmp wewnątrz chroot
cp -r /cdrom/robloxos /tmp/robloxos

# Sprawdź internet
curl -s https://flathub.org > /dev/null && echo "Internet: OK" || echo "Internet: BRAK"
```

### 4b. Zainstaluj dodatkowe pakiety (opcjonalnie)

```bash
# Aktualizacja listy pakietów
apt-get update -qq

# Dodatkowe pakiety jeśli nie są w user-data
apt-get install -y python3-pyqt6 picom unclutter wmctrl \
    flatpak apparmor apparmor-utils python3-psutil
```

### 4c. Uruchom główny skrypt konfiguracyjny

```bash
chmod +x /tmp/robloxos/iso/chroot-setup.sh
bash /tmp/robloxos/iso/chroot-setup.sh
```

Skrypt zajmie **5-20 minut** (zależnie od prędkości internetu dla Flatpak).
Obserwuj output – zielone `[OK]` przy każdym kroku.

### 4d. Weryfikacja po chroot-setup.sh

```bash
# Sprawdź usera
id robloxuser
getent passwd robloxuser | cut -d: -f7   # powinno być /usr/sbin/nologin

# Sprawdź LightDM
cat /etc/lightdm/lightdm.conf | grep autologin

# Sprawdź AppArmor
aa-status 2>/dev/null | grep robloxos || echo "AppArmor załaduje profile po restarcie"

# Sprawdź Flatpak
flatpak list --system

# Sprawdź launcher
python3 /home/robloxuser/launcher/launcher.py --version 2>/dev/null || \
    python3 -c "import PyQt6; print('PyQt6 OK')"
```

---

## Krok 5 – Preseed / autoinstall

Aby ISO instalowało się automatycznie (bez pytań):

W terminalu Cubic dodaj plik autoinstall:

```bash
mkdir -p /iso/autoinstall
cp /tmp/robloxos/iso/preseed/user-data /iso/autoinstall/
cp /tmp/robloxos/iso/preseed/meta-data /iso/autoinstall/

# WAŻNE: Zmień hash hasła w user-data!
nano /iso/autoinstall/user-data
# Znajdź linię: password: "$6$ZMIEN_TO$..."
# Zastąp hashem: openssl passwd -6 'TwojeHaslo'
```

Zmodyfikuj też linię grub (parametry jądra) w Cubic:

```
Oryginalna: quiet splash ---
Nowa:       quiet splash autoinstall ds=nocloud\;s=/cdrom/autoinstall/ ---
```

(W zakładce **Boot** Cubic możesz edytować parametry GRUB/Syslinux)

---

## Krok 6 – Generowanie ISO

1. Kliknij **Next** w Cubic
2. Wybierz pakiety do usunięcia (opcjonalnie – możesz pominąć)
3. **Compression**: wybierz `xz` (mniejszy ISO, wolniejszy build) lub `lzo` (szybszy)
4. Kliknij **Generate**

Build zajmie **10-30 minut**.

Gotowy ISO będzie w katalogu projektu Cubic (np. `/home/user/robloxos-build/robloxos-1.0-amd64.iso`).

---

## Krok 7 – Test w VirtualBox / QEMU

Przed wgraniem na USB przetestuj w VM:

### QEMU (szybszy)

```bash
# Utwórz wirtualny dysk 30 GB
qemu-img create -f qcow2 robloxos-test.qcow2 30G

# Uruchom z ISO (z oknem)
qemu-system-x86_64 \
    -m 4096 -smp 2 -enable-kvm \
    -drive file=robloxos-test.qcow2,format=qcow2 \
    -cdrom robloxos-1.0-amd64.iso \
    -boot d -vga virtio -display sdl

# lub: make test-gui
```

### VirtualBox

1. Nowa VM → Ubuntu 64-bit → 4GB RAM → 30GB dysk
2. Ustawienia → System → włącz EFI
3. Ustawienia → Display → 128MB VRAM + 3D acceleration
4. Ustawienia → Storage → dołącz ISO jako napęd optyczny
5. Start

---

## Krok 8 – Wgranie na USB

```bash
# Przez Makefile (bezpieczne – pyta o potwierdzenie):
make usb

# Ręcznie (UWAŻAJ na /dev/sdX – złe urządzenie = utrata danych!):
sudo dd if=robloxos-1.0-amd64.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

---

## Znane problemy i rozwiązania

| Problem | Przyczyna | Rozwiązanie |
|---------|-----------|-------------|
| Launcher nie startuje | Brak PyQt6 | `pip install PyQt6` w venv |
| Discord nie wykrywa monitora | wmctrl nie zainstalowany | `apt install wmctrl` |
| Chromium nie ładuje extension | Zła ścieżka w CMD | Sprawdź `--load-extension=` w launcher.py |
| AppArmor blokuje launcher | Profil zbyt restrykcyjny | `aa-complain robloxos.launcher` do debugowania |
| Flatpak nie działa | Brak repozytorium | `flatpak remote-add --system flathub ...` |
| Czarny ekran po loginie | .xsession błąd | `journalctl -u lightdm` |
| Sober nie widzi GPU | Brak sterowników | Zainstaluj sterowniki NVIDIA/AMD po starcie |

---

## Po zainstalowaniu na docelowym sprzęcie

```bash
# Zaloguj się jako root (fizycznie lub przez TTY Ctrl+Alt+F2)

# Zainstaluj Discord i Sober jeśli pominięto podczas buildu:
flatpak remote-add --system --if-not-exists flathub \
    https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --system flathub com.discordapp.Discord
flatpak install --system flathub org.vinegarhq.Sober

# Zaktualizuj komendę Sober w launcher.py jeśli potrzeba:
# APPS["roblox"]["cmd"] = ["flatpak", "run", "org.vinegarhq.Sober"]

# Sprawdź status watchdoga:
systemctl status robloxos-watchdog
tail -f /var/log/robloxos-watchdog.log
```
