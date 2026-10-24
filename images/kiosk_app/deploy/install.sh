#!/bin/bash
# One-time setup on the Raspberry Pi (Raspberry Pi OS 64-bit, desktop version).
# Run from the kiosk_app folder:   bash deploy/install.sh
set -e
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"

echo "== System packages"
sudo apt update
# picamera2 is only installable through apt, so the venv below can see system packages.
sudo apt install -y python3-venv python3-picamera2 curl

echo "== Python environment"
python3 -m venv --system-site-packages "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "== Server starts on boot (systemd)"
sudo tee /etc/systemd/system/lab-kiosk.service > /dev/null <<EOF
[Unit]
Description=Lab component kiosk server
After=network.target

[Service]
User=$USER_NAME
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now lab-kiosk.service

echo "== Browser opens full-screen at login"
chmod +x "$APP_DIR/deploy/start_browser.sh"
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/lab-kiosk.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Lab Kiosk
Exec=$APP_DIR/deploy/start_browser.sh
EOF

echo "== Desktop login without password, screen never blanks"
sudo raspi-config nonint do_boot_behaviour B4 || true
sudo raspi-config nonint do_blanking 1 || true

echo
echo "Done. Check the server with:  systemctl status lab-kiosk"
echo "Logs:                          journalctl -u lab-kiosk -f"
echo "Reboot to start in kiosk mode: sudo reboot"
