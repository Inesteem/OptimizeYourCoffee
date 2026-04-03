#!/bin/bash
# Safe deploy: stops Flask before copying, preserves database
set -euo pipefail

if [ ! -f deploy.conf ]; then
    echo "Error: deploy.conf not found. Copy deploy.conf.example and fill in your details."
    exit 1
fi
source deploy.conf

echo "Stopping Flask on Pi..."
ssh $PI_USER@$PI_HOST "sudo systemctl stop coffee-kiosk.service" 2>/dev/null || true
sleep 1

echo "Deploying files (excluding database)..."
rsync -av --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' \
    --exclude='backups/' --exclude='.secret_key' --exclude='__pycache__/' \
    coffee-app/ $PI_USER@$PI_HOST:$PI_APP_DIR/

echo "Restarting..."
ssh $PI_USER@$PI_HOST "bash $PI_APP_DIR/restart-ui.sh"
echo "Done."
