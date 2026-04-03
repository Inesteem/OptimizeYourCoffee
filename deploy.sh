#!/bin/bash
# Safe deploy: backup DB, stop Flask, copy files, restart
set -euo pipefail

if [ ! -f deploy.conf ]; then
    echo "Error: deploy.conf not found. Copy deploy.conf.example and fill in your details."
    exit 1
fi
source deploy.conf

echo "1/4 Backing up database on Pi..."
ssh $PI_USER@$PI_HOST "mkdir -p $PI_APP_DIR/backups && cp $PI_APP_DIR/coffee.db $PI_APP_DIR/backups/coffee-\$(date +%Y-%m-%d_%H%M%S).db 2>/dev/null && echo 'Backup created' || echo 'No DB to backup (fresh install)'"

echo "2/4 Stopping Flask..."
ssh $PI_USER@$PI_HOST "sudo systemctl stop coffee-kiosk.service" 2>/dev/null || true
sleep 1

echo "3/4 Deploying files (excluding database)..."
rsync -av --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' \
    --exclude='backups/' --exclude='.secret_key' --exclude='__pycache__/' \
    coffee-app/ $PI_USER@$PI_HOST:$PI_APP_DIR/

echo "4/4 Restarting..."
ssh $PI_USER@$PI_HOST "bash $PI_APP_DIR/restart-ui.sh"
echo "Done. Database preserved."
