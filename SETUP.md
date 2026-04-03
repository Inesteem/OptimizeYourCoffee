# Setup Guide — Coffee Sampler on Raspberry Pi

## Hardware Required

- **Raspberry Pi 4 Model B** (8GB recommended, 4GB minimum)
- **Official Raspberry Pi 7" Touchscreen Display** (800x480, DSI connector, capacitive touch)
- **MicroSD card** (16GB+, 64-bit Raspberry Pi OS)
- **Power supply** (USB-C, 5V/3A for Pi 4)
- **Optional**: Ethernet cable (or WiFi)

## 1. Flash the SD Card

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to flash **Raspberry Pi OS (64-bit)** to the SD card.

Alternatively, use the included `setup-rpi-sd.sh` script to configure a pre-flashed card:

```bash
sudo ./setup-rpi-sd.sh /dev/sdX
```

This enables SSH, configures WiFi (optional), creates a user, and verifies display config.

## 2. Connect the Touchscreen

1. Connect the DSI ribbon cable from the Pi to the display
2. Connect the display's power/touch USB cable to the Pi
3. The display should work out of the box with Raspberry Pi OS

## 3. Boot and Connect via SSH

```bash
# Find your Pi on the network
ping raspberrypi.local
# Or scan: nmap -sn 192.168.x.0/24

# SSH in
ssh <user>@<pi-ip>
```

## 4. Install Dependencies

```bash
# Emoji font (required for tasting note display)
sudo apt install -y fonts-noto-color-emoji

# Python packages (Flask and numpy should be pre-installed on Pi OS)
python3 --version  # Should be 3.11+
python3 -c "import flask; print(flask.__version__)"
python3 -c "import numpy; print(numpy.__version__)"

# If missing:
sudo apt install -y python3-flask python3-numpy
```

## 5. Deploy the App

Copy `deploy.conf.example` to `deploy.conf` and fill in your Pi details:

```
PI_USER=youruser
PI_HOST=192.168.x.x
PI_APP_DIR=/home/youruser/coffee-app
```

Then deploy:

```bash
source deploy.conf
ssh $PI_USER@$PI_HOST "mkdir -p $PI_APP_DIR"
scp -r coffee-app/* $PI_USER@$PI_HOST:$PI_APP_DIR/
```

## 6. Install the systemd Service

```bash
source deploy.conf

# Copy and configure the service file
ssh $PI_USER@$PI_HOST "sed 's/DEPLOY_USER/$PI_USER/g' $PI_APP_DIR/coffee-kiosk.service | sudo tee /etc/systemd/system/coffee-kiosk.service"
ssh $PI_USER@$PI_HOST "sudo systemctl daemon-reload && sudo systemctl enable coffee-kiosk.service && sudo systemctl start coffee-kiosk.service"
```

Verify it's running:

```bash
ssh $PI_USER@$PI_HOST "sudo systemctl status coffee-kiosk.service"
```

## 7. Set Up Chromium Kiosk Autostart

```bash
source deploy.conf
ssh $PI_USER@$PI_HOST 'mkdir -p ~/.config/autostart && cat > ~/.config/autostart/coffee-kiosk.desktop << "EOF"
[Desktop Entry]
Type=Application
Name=Coffee Kiosk
Exec=bash -c "sleep 5 && chromium --ozone-platform=wayland --enable-wayland-ime --disk-cache-size=1 --aggressive-cache-discard --kiosk --noerrdialogs --disable-infobars --no-first-run --enable-touch-events http://localhost:5000"
X-GNOME-Autostart-enabled=true
EOF'
```

## 8. Set Up Desktop Shortcut (optional)

For relaunching after quitting the kiosk:

```bash
source deploy.conf
ssh $PI_USER@$PI_HOST "cp $PI_APP_DIR/static/coffee-bean.svg ~/Desktop/ 2>/dev/null"
ssh $PI_USER@$PI_HOST 'cat > ~/Desktop/coffee-sampler.desktop << "EOF"
[Desktop Entry]
Type=Application
Name=Coffee Sampler
Exec=bash -c "chromium --ozone-platform=wayland --enable-wayland-ime --disk-cache-size=1 --aggressive-cache-discard --kiosk --noerrdialogs --disable-infobars --no-first-run --enable-touch-events http://localhost:5000"
Icon=/home/'$PI_USER'/coffee-app/static/coffee-bean.svg
Terminal=false
EOF
chmod +x ~/Desktop/coffee-sampler.desktop'
```

## 9. Enable Autologin (optional)

Skip the login screen on boot:

```bash
source deploy.conf
ssh $PI_USER@$PI_HOST "sudo groupadd -f autologin && sudo usermod -aG autologin $PI_USER"
```

LightDM should already have `autologin-user` set if you configured it during imaging.

## 10. Set Up SSH Key Auth (recommended)

```bash
source deploy.conf
ssh-copy-id $PI_USER@$PI_HOST
```

## 11. Reboot

```bash
source deploy.conf
ssh $PI_USER@$PI_HOST "sudo reboot"
```

The app should auto-launch in kiosk mode on the touchscreen after ~20 seconds.

## Updating the App

```bash
source deploy.conf
scp -r coffee-app/* $PI_USER@$PI_HOST:$PI_APP_DIR/
ssh $PI_USER@$PI_HOST "bash $PI_APP_DIR/restart-ui.sh"
```

## Troubleshooting

### App doesn't start
```bash
ssh $PI_USER@$PI_HOST "sudo journalctl -u coffee-kiosk.service -n 20"
```

### Chromium shows white screen
- Check if Flask is running: `curl http://localhost:5000/`
- Kiosk may have launched before Flask — reboot

### Touchscreen not working
- Check DSI connection
- Verify display: `DISPLAY=:0 xrandr`

### Virtual keyboard not appearing
- Chromium kiosk mode may not trigger squeekboard — the app includes its own on-screen keyboard

### Known Chromium/Wayland issues
- `position: fixed` elements with `display: none/block` toggle won't repaint — app uses `:empty` collapse pattern instead
- Cache is aggressive — disabled via `--disk-cache-size=1`

## File Structure

```
coffee-settings/
├── coffee-app/
│   ├── app.py                  # Flask application (~1100 lines)
│   ├── coffee-kiosk.service    # systemd service template
│   ├── restart-ui.sh           # Helper to restart Flask + Chromium
│   ├── static/                 # CSS, JS, fonts, icons
│   └── templates/              # Jinja2 HTML templates
├── reference/                  # Research docs, review notes, roadmap
├── tests/                      # pytest test suite (108 tests)
├── setup-rpi-sd.sh            # SD card setup script
├── deploy.conf                # Pi credentials (gitignored)
├── SETUP.md                   # This file
└── README.md                  # Feature overview
```
