# RobloxOS – Makefile
# Automatyzacja pipeline'u budowania ISO.
#
# Użycie:
#   make deps      – zainstaluj zależności na maszynie buildowej
#   make iso       – zbuduj custom ISO (pełny pipeline)
#   make test      – przetestuj ISO w QEMU
#   make usb       – wgraj ISO na USB (pyta o potwierdzenie!)
#   make clean     – usuń pliki tymczasowe
#   make help      – pokaż ten help
#
# Wymagania maszyny buildowej:
#   - Ubuntu 22.04 (lub 20.04/24.04)
#   - ~20 GB wolnego miejsca
#   - Internet (Cubic, base ISO)
#
# UWAGA: 'make usb' jest NIEODWRACALNE. Dane na wybranym urządzeniu
#        zostaną TRWALE USUNIĘTE.

# ── Zmienne ───────────────────────────────────────────────────────────────────
PROJECT_ROOT := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
ISO_DIR      := $(PROJECT_ROOT)
BUILD_DIR    := $(PROJECT_ROOT)/build
OUTPUT_DIR   := $(PROJECT_ROOT)/output

# Bazowy ISO Ubuntu 22.04 LTS
BASE_ISO_URL  := https://releases.ubuntu.com/22.04/ubuntu-22.04.4-desktop-amd64.iso
BASE_ISO_NAME := ubuntu-22.04.4-desktop-amd64.iso
BASE_ISO_PATH := $(BUILD_DIR)/$(BASE_ISO_NAME)

# Gotowy ISO RobloxOS
OUTPUT_ISO   := $(OUTPUT_DIR)/robloxos-1.0-amd64.iso

# Cubic – projekt (katalog roboczy Cubic)
CUBIC_PROJECT := $(BUILD_DIR)/cubic-project

# QEMU – parametry testowe
QEMU_RAM     := 4096    # MB
QEMU_CPUS    := 2
QEMU_DISK    := $(BUILD_DIR)/test-disk.qcow2
QEMU_DISK_GB := 30

.PHONY: all help deps iso test usb clean check-root

all: help

# ── Help ──────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  RobloxOS Build System"
	@echo "  ─────────────────────────────────────────────────────────────"
	@echo "  make deps      Zainstaluj zależności buildowe"
	@echo "  make iso       Zbuduj custom ISO (wymaga Cubic GUI)"
	@echo "  make iso-auto  Zbuduj ISO automatycznie (bez GUI, przez xorriso)"
	@echo "  make test      Przetestuj ISO w QEMU (headless)"
	@echo "  make test-gui  Przetestuj ISO w QEMU (z oknem)"
	@echo "  make usb       Wgraj ISO na USB (!!! NIEODWRACALNE !!!)"
	@echo "  make clean     Usuń pliki tymczasowe (zachowuje output/)"
	@echo "  make distclean Usuń WSZYSTKO włącznie z output/"
	@echo "  ─────────────────────────────────────────────────────────────"
	@echo ""

# ── Sprawdź root ──────────────────────────────────────────────────────────────
check-root:
	@if [ "$$(id -u)" -ne 0 ]; then \
		echo "BŁĄD: Ten cel wymaga uprawnień root (sudo make $@)"; \
		exit 1; \
	fi

# ── Zależności buildowe ───────────────────────────────────────────────────────
deps:
	@echo "[deps] Instaluję zależności buildowe..."
	sudo apt-get update -qq
	sudo apt-get install -y --no-install-recommends \
		squashfs-tools \
		genisoimage \
		xorriso \
		isolinux \
		syslinux-utils \
		grub-pc-bin \
		grub-efi-amd64-bin \
		mtools \
		curl \
		wget \
		qemu-system-x86 \
		qemu-utils \
		ovmf \
		python3 \
		python3-pip
	# Cubic – instalacja przez PPA
	@echo "[deps] Instaluję Cubic..."
	sudo apt-add-repository -y ppa:cubic-wizard/release 2>/dev/null || true
	sudo apt-get update -qq
	sudo apt-get install -y cubic || \
		echo "UWAGA: Cubic niedostępny – użyj 'make iso-auto' zamiast 'make iso'"
	@echo "[deps] Gotowe."

# ── Pobierz base ISO ──────────────────────────────────────────────────────────
$(BASE_ISO_PATH):
	@echo "[iso] Pobieram bazowy Ubuntu 22.04 ISO (~1.4 GB)..."
	@mkdir -p $(BUILD_DIR)
	wget --show-progress -c -O "$@" "$(BASE_ISO_URL)"
	@echo "[iso] Weryfikuję sumę kontrolną..."
	@echo "45f873de9f8cb637345d6e66a583762730bbea30277ef7b32c9c3bd6700a32b *$(BASE_ISO_NAME)" \
		| sha256sum -c - || (echo "BŁĄD: Suma kontrolna nie zgadza się!" && rm "$@" && exit 1)
	@echo "[iso] ISO pobrane i zweryfikowane."

# ── ISO (Cubic GUI) ───────────────────────────────────────────────────────────
iso: $(BASE_ISO_PATH)
	@echo ""
	@echo "════════════════════════════════════════════════════════════"
	@echo "  Budowanie ISO przez Cubic (GUI)"
	@echo "════════════════════════════════════════════════════════════"
	@echo ""
	@echo "  Cubic otworzy się zaraz. Wykonaj kroki:"
	@echo "  1. Wybierz katalog projektu: $(CUBIC_PROJECT)"
	@echo "  2. Wskaż bazowy ISO: $(BASE_ISO_PATH)"
	@echo "  3. Ustaw nazwę ISO: robloxos-1.0-amd64"
	@echo "  4. W terminalu Cubic:"
	@echo "     cp -r /cdrom/robloxos-setup /tmp/robloxos"
	@echo "     bash /tmp/robloxos/chroot-setup.sh"
	@echo "  5. Kliknij Next → Compression: xz → Generate"
	@echo "  6. Skopiuj wynikowy ISO do: $(OUTPUT_DIR)/"
	@echo ""
	@mkdir -p $(CUBIC_PROJECT) $(OUTPUT_DIR)
	# Kopiuj pliki projektu do katalogu który Cubic dołączy do ISO
	@mkdir -p "$(CUBIC_PROJECT)/robloxos-setup"
	@cp -r $(PROJECT_ROOT)/../launcher  "$(CUBIC_PROJECT)/robloxos-setup/"
	@cp -r $(PROJECT_ROOT)/../openbox   "$(CUBIC_PROJECT)/robloxos-setup/"
	@cp -r $(PROJECT_ROOT)/../browser   "$(CUBIC_PROJECT)/robloxos-setup/"
	@cp -r $(PROJECT_ROOT)/../security  "$(CUBIC_PROJECT)/robloxos-setup/"
	@cp    $(ISO_DIR)/chroot-setup.sh   "$(CUBIC_PROJECT)/robloxos-setup/"
	@cp -r $(ISO_DIR)/lightdm           "$(CUBIC_PROJECT)/robloxos-setup/"
	@cp -r $(ISO_DIR)/preseed           "$(CUBIC_PROJECT)/robloxos-setup/"
	@echo "  Pliki projektu skopiowane do: $(CUBIC_PROJECT)/robloxos-setup/"
	@echo ""
	@read -p "Naciśnij Enter aby otworzyć Cubic..." _dummy
	cubic $(CUBIC_PROJECT) || echo "Cubic nie jest zainstalowany – użyj 'make iso-auto'"

# ── ISO (automatyczny, bez GUI – xorriso) ────────────────────────────────────
iso-auto: $(BASE_ISO_PATH)
	@echo "[iso-auto] Budowanie ISO bez GUI..."
	@mkdir -p $(BUILD_DIR)/iso-extract $(OUTPUT_DIR)
	# Wypakuj bazowy ISO
	xorriso -osirrox on \
		-indev "$(BASE_ISO_PATH)" \
		-extract / "$(BUILD_DIR)/iso-extract" 2>/dev/null || \
		(cd $(BUILD_DIR) && 7z x -o"iso-extract" "$(BASE_ISO_PATH)" > /dev/null)
	# Wgraj autoinstall preseed
	mkdir -p "$(BUILD_DIR)/iso-extract/autoinstall"
	cp "$(ISO_DIR)/preseed/user-data" "$(BUILD_DIR)/iso-extract/autoinstall/"
	cp "$(ISO_DIR)/preseed/meta-data" "$(BUILD_DIR)/iso-extract/autoinstall/"
	# Wgraj pliki projektu
	mkdir -p "$(BUILD_DIR)/iso-extract/robloxos-setup"
	cp -r $(PROJECT_ROOT)/../launcher  "$(BUILD_DIR)/iso-extract/robloxos-setup/"
	cp -r $(PROJECT_ROOT)/../openbox   "$(BUILD_DIR)/iso-extract/robloxos-setup/"
	cp -r $(PROJECT_ROOT)/../browser   "$(BUILD_DIR)/iso-extract/robloxos-setup/"
	cp -r $(PROJECT_ROOT)/../security  "$(BUILD_DIR)/iso-extract/robloxos-setup/"
	cp    $(ISO_DIR)/chroot-setup.sh   "$(BUILD_DIR)/iso-extract/robloxos-setup/"
	cp -r $(ISO_DIR)/lightdm           "$(BUILD_DIR)/iso-extract/robloxos-setup/"
	# Zbuduj nowy ISO
	xorriso -as mkisofs \
		-r -V "RobloxOS 1.0" \
		-o "$(OUTPUT_ISO)" \
		-J -joliet-long \
		-b isolinux/isolinux.bin \
		-c isolinux/boot.cat \
		-no-emul-boot \
		-boot-load-size 4 \
		-boot-info-table \
		--efi-boot boot/grub/efi.img \
		-efi-boot-part --efi-boot-image \
		"$(BUILD_DIR)/iso-extract" 2>&1 | tail -5
	@echo "[iso-auto] ISO gotowy: $(OUTPUT_ISO)"
	@ls -lh "$(OUTPUT_ISO)"

# ── Test w QEMU ───────────────────────────────────────────────────────────────
$(QEMU_DISK):
	@echo "[test] Tworzę wirtualny dysk $(QEMU_DISK_GB) GB..."
	qemu-img create -f qcow2 "$(QEMU_DISK)" "$(QEMU_DISK_GB)G"

test: $(QEMU_DISK)
	@test -f "$(OUTPUT_ISO)" || (echo "BŁĄD: Brak ISO. Uruchom najpierw: make iso" && exit 1)
	@echo "[test] Uruchamiam QEMU (headless – VNC na :5900)..."
	@echo "       Połącz się przez: vncviewer localhost:5900"
	qemu-system-x86_64 \
		-name "RobloxOS Test" \
		-m $(QEMU_RAM) \
		-smp $(QEMU_CPUS) \
		-enable-kvm \
		-drive file="$(QEMU_DISK)",format=qcow2 \
		-cdrom "$(OUTPUT_ISO)" \
		-boot d \
		-bios /usr/share/ovmf/OVMF.fd \
		-vnc :0 \
		-net nic,model=virtio \
		-net user \
		-vga virtio \
		-daemonize \
		-pidfile $(BUILD_DIR)/qemu.pid
	@echo "[test] QEMU uruchomiony (PID: $$(cat $(BUILD_DIR)/qemu.pid))"
	@echo "       Zatrzymaj: kill $$(cat $(BUILD_DIR)/qemu.pid)"

test-gui: $(QEMU_DISK)
	@test -f "$(OUTPUT_ISO)" || (echo "BŁĄD: Brak ISO. Uruchom najpierw: make iso" && exit 1)
	@echo "[test-gui] Uruchamiam QEMU z oknem SDL..."
	qemu-system-x86_64 \
		-name "RobloxOS Test" \
		-m $(QEMU_RAM) \
		-smp $(QEMU_CPUS) \
		-enable-kvm \
		-drive file="$(QEMU_DISK)",format=qcow2 \
		-cdrom "$(OUTPUT_ISO)" \
		-boot d \
		-bios /usr/share/ovmf/OVMF.fd \
		-net nic,model=virtio \
		-net user \
		-vga virtio \
		-display sdl

# ── USB flash ─────────────────────────────────════════════════════════════════
usb:
	@test -f "$(OUTPUT_ISO)" || (echo "BŁĄD: Brak ISO. Uruchom najpierw: make iso" && exit 1)
	@echo ""
	@echo "  ╔══════════════════════════════════════════════════════╗"
	@echo "  ║  UWAGA: Operacja NIEODWRACALNA!                     ║"
	@echo "  ║  Wszystkie dane na wybranym nośniku zostaną USUNIĘTE║"
	@echo "  ╚══════════════════════════════════════════════════════╝"
	@echo ""
	@lsblk -d -o NAME,SIZE,MODEL | grep -v loop
	@echo ""
	@read -p "  Podaj urządzenie USB (np. sdb, NIE sdb1): " USB_DEV && \
	USB_PATH="/dev/$$USB_DEV" && \
	if [ ! -b "$$USB_PATH" ]; then \
		echo "BŁĄD: $$USB_PATH nie istnieje lub nie jest urządzeniem blokowym."; \
		exit 1; \
	fi && \
	echo "" && \
	echo "  ISO:     $(OUTPUT_ISO)" && \
	echo "  Nośnik:  $$USB_PATH ($$(lsblk -dn -o SIZE $$USB_PATH))" && \
	echo "" && \
	read -p "  Wpisz 'tak' aby potwierdzić: " CONFIRM && \
	if [ "$$CONFIRM" != "tak" ]; then \
		echo "Anulowano."; \
		exit 0; \
	fi && \
	echo "[usb] Zapisuję ISO na $$USB_PATH..." && \
	sudo dd if="$(OUTPUT_ISO)" of="$$USB_PATH" bs=4M status=progress oflag=sync && \
	echo "[usb] Synchronizuję bufor..." && \
	sync && \
	echo "[usb] Gotowe! Możesz wyjąć nośnik."

# ── Czyszczenie ───────────────────────────────────────────────────────────────
clean:
	@echo "[clean] Usuwam pliki tymczasowe (zachowuję output/ i base ISO)..."
	rm -rf "$(BUILD_DIR)/iso-extract"
	rm -rf "$(BUILD_DIR)/cubic-project"
	rm -f  "$(QEMU_DISK)"
	rm -f  "$(BUILD_DIR)/qemu.pid"
	@echo "[clean] Gotowe."

distclean: clean
	@echo "[distclean] Usuwam WSZYSTKO (output/ + base ISO)..."
	rm -rf "$(BUILD_DIR)"
	rm -rf "$(OUTPUT_DIR)"
	@echo "[distclean] Gotowe."
