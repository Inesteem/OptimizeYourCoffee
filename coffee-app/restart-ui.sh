#!/bin/bash
# Restart Flask + Chromium safely (preserves database)
export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-0

sudo systemctl restart coffee-kiosk.service
sleep 1

pkill -f chromium 2>/dev/null
sleep 2
nohup chromium --ozone-platform=wayland --enable-wayland-ime --disk-cache-size=1 --aggressive-cache-discard --kiosk --noerrdialogs --disable-infobars --no-first-run --enable-touch-events http://localhost:5000 > /dev/null 2>&1 &
echo "Chromium restarted (cache disabled)"
