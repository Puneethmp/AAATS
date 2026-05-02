#!/bin/bash
# AAATS One-Command Deployment Script
# Deploys AAATS to Oracle Cloud Free Tier with systemd auto-start

set -e

AAATS_DIR="/home/ubuntu/aaats"
SYSTEMD_DIR="/etc/systemd/system"

echo "=========================================="
echo "AAATS Deployment Script"
echo "Oracle Cloud Free Tier Optimized"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: Please run as root (use sudo)"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed"
    echo "Install Docker first: https://docs.docker.com/engine/install/ubuntu/"
    exit 1
fi

# Check if Docker Compose is installed
if ! docker compose version &> /dev/null; then
    echo "ERROR: Docker Compose is not installed"
    exit 1
fi

echo "[1/6] Validating environment..."
if [ ! -f "$AAATS_DIR/.env" ]; then
    echo "ERROR: .env file not found at $AAATS_DIR/.env"
    echo "Copy config/.env.example to .env and configure it first"
    exit 1
fi
echo "✓ Environment file found"

echo ""
echo "[2/6] Building Docker images..."
cd "$AAATS_DIR"
docker compose -f deployment/docker-compose.yml build
echo "✓ Docker images built"

echo ""
echo "[3/6] Installing systemd services..."
cp deployment/systemd/*.service "$SYSTEMD_DIR/"
systemctl daemon-reload
echo "✓ Systemd services installed"

echo ""
echo "[4/6] Enabling auto-start on boot..."
systemctl enable aaats-paper-us.service
systemctl enable aaats-paper-india.service
systemctl enable aaats-paper-crypto.service
systemctl enable aaats-dashboard.service
echo "✓ Auto-start enabled"

echo ""
echo "[5/6] Starting services..."
systemctl start aaats-paper-us.service
systemctl start aaats-paper-india.service
systemctl start aaats-paper-crypto.service
systemctl start aaats-dashboard.service
echo "✓ Services started"

echo ""
echo "[6/6] Setting up automated backups..."
chmod +x deployment/scripts/backup.sh
# Add daily backup cron job (3 AM)
(crontab -l 2>/dev/null | grep -v "aaats-backup"; echo "0 3 * * * $AAATS_DIR/deployment/scripts/backup.sh >> /var/log/aaats-backup.log 2>&1") | crontab -
echo "✓ Daily backups configured (3 AM)"

echo ""
echo "=========================================="
echo "DEPLOYMENT COMPLETE!"
echo "=========================================="
echo ""
echo "Service Status:"
systemctl status aaats-paper-us.service --no-pager -l | head -3
systemctl status aaats-paper-india.service --no-pager -l | head -3
systemctl status aaats-paper-crypto.service --no-pager -l | head -3
systemctl status aaats-dashboard.service --no-pager -l | head -3
echo ""
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8501"
echo ""
echo "Useful commands:"
echo "  View logs:        journalctl -u aaats-paper-us -f"
echo "  Restart service:  sudo systemctl restart aaats-paper-us"
echo "  Stop all:         sudo systemctl stop aaats-*"
echo "  Check status:     sudo systemctl status aaats-*"
echo ""
