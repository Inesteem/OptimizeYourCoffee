#!/bin/bash
set -euo pipefail

DEVICE="${1:-/dev/sdb}"
BOOT_MNT="/mnt/rpi-boot"
ROOT_MNT="/mnt/rpi-root"

if [[ $EUID -ne 0 ]]; then
    echo "This script must be run as root (use sudo)."
    exit 1
fi

echo "=== Raspberry Pi SD Card SSH Setup ==="
echo "Using device: ${DEVICE}"
echo

# --- Mount partitions ---
mkdir -p "$BOOT_MNT" "$ROOT_MNT"
mount "${DEVICE}1" "$BOOT_MNT"
mount "${DEVICE}2" "$ROOT_MNT"
echo "[OK] Partitions mounted."

cleanup() {
    echo
    echo "Unmounting partitions..."
    umount "$BOOT_MNT" 2>/dev/null || true
    umount "$ROOT_MNT" 2>/dev/null || true
    echo "[OK] Done. You can remove the SD card."
}
trap cleanup EXIT

# --- Enable SSH ---
touch "$BOOT_MNT/ssh"
echo "[OK] SSH enabled."

# --- User setup ---
read -rp "Did you already configure a user during imaging? [y/N]: " user_done
if [[ "${user_done,,}" != "y" ]]; then
    read -rp "Enter username: " rpi_user
    read -rsp "Enter password: " rpi_pass
    echo
    encrypted=$(openssl passwd -6 "$rpi_pass")
    echo "${rpi_user}:${encrypted}" > "$BOOT_MNT/userconf.txt"
    echo "[OK] User '${rpi_user}' configured."
fi

# --- WiFi setup ---
read -rp "Configure WiFi? [y/N]: " setup_wifi
if [[ "${setup_wifi,,}" == "y" ]]; then
    read -rp "WiFi country code (e.g. US, GB, DE): " wifi_country
    read -rp "WiFi SSID: " wifi_ssid
    read -rsp "WiFi password: " wifi_pass
    echo
    cat > "$BOOT_MNT/wpa_supplicant.conf" <<EOF
country=${wifi_country}
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={
    ssid="${wifi_ssid}"
    psk="${wifi_pass}"
}
EOF
    echo "[OK] WiFi configured."
else
    echo "[--] Skipping WiFi (using Ethernet)."
fi

# --- Touchscreen config ---
read -rp "Enable official 7\" touchscreen display? [Y/n]: " setup_display
if [[ "${setup_display,,}" != "n" ]]; then
    if ! grep -q "dtoverlay=vc4-kms-v3d" "$BOOT_MNT/config.txt" 2>/dev/null; then
        echo "dtoverlay=vc4-kms-v3d" >> "$BOOT_MNT/config.txt"
    fi
    echo "[OK] Display config verified."
fi

echo
echo "=== Setup complete ==="
echo "Insert the SD card into your Pi and boot it."
echo "Find it on your network with: nmap -sn 192.168.1.0/24"
echo "Then connect with: ssh <username>@<pi-ip>"
