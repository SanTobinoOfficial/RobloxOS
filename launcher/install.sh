#!/usr/bin/env bash
# RobloxOS – Launcher install script
# Run as root on Ubuntu 22.04

set -euo pipefail

INSTALL_DIR="/opt/robloxos"
LAUNCHER_USER="robloxos"   # dedicated unprivileged user

# ── Dependencies ──────────────────────────────────────────────────────────────
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3-pip \
    python3-pyqt6 \
    wmctrl \
    x11-xserver-utils   # provides xrandr

# ── Create install directory ──────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
cp launcher.py        "$INSTALL_DIR/launcher.py"
cp discord_launcher.py "$INSTALL_DIR/discord_launcher.py"
chmod 755 "$INSTALL_DIR/launcher.py"
chmod 755 "$INSTALL_DIR/discord_launcher.py"

# ── Systemd user service (auto-starts launcher after login) ──────────────────
SERVICE_DIR="/etc/systemd/user"
mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_DIR/robloxos-launcher.service" <<EOF
[Unit]
Description=RobloxOS Launcher
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/launcher.py
Restart=always
RestartSec=3
Environment=DISPLAY=:0
Environment=XDG_RUNTIME_DIR=/run/user/%U

[Install]
WantedBy=graphical-session.target
EOF

systemctl daemon-reload
echo "[install] Done. Enable with: systemctl --user enable --now robloxos-launcher"
