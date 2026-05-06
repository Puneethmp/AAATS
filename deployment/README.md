# AAATS Deployment Guide

Oracle Cloud Free Tier optimized deployment with Docker, systemd auto-start, and autonomous recovery.

## Quick Start

### Prerequisites

1. Oracle Cloud Free Tier VM (Ubuntu 22.04 LTS)
2. Docker and Docker Compose installed
3. Git installed
4. Configured `.env` file

### One-Command Deployment

```bash
# Clone repository
git clone https://github.com/Puneethmp/AAATS.git
cd AAATS

# Configure environment
cp config/.env.example .env
nano .env  # Edit with your API keys

# Validate configuration
python deployment/scripts/validate_env.py

# Deploy (requires sudo)
sudo bash deployment/scripts/deploy.sh
```

That's it! AAATS will now:
- Run autonomously 24/7
- Auto-restart on crashes
- Auto-start on VM reboot
- Backup daily at 3 AM
- Rotate logs automatically

---

## Architecture

### Services

| Service | Description | Port | Auto-Start |
|---------|-------------|------|------------|
| `aaats-paper-us` | US markets paper trading | - | Yes |
| `aaats-paper-india` | India markets paper trading | - | Yes |
| `aaats-paper-crypto` | Crypto markets paper trading | - | Yes |
| `aaats-dashboard` | Streamlit web dashboard | 8501 | Yes |

### Resource Limits (Oracle Free Tier Optimized)

Each service:
- CPU: 0.25-0.5 cores
- RAM: 256-512 MB
- Total: ~2 GB RAM, 2 CPU cores

---

## Manual Deployment Steps

If you prefer step-by-step deployment:

### 1. Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Verify installation
docker --version
docker compose version
```

### 2. Configure Environment

```bash
cd /home/ubuntu/aaats
cp config/.env.example .env
nano .env
```

Required variables:
```bash
# System
SYSTEM__TRADING_MODE=paper
SYSTEM__LOG_LEVEL=INFO

# US Market (Alpaca)
US__ALPACA_API_KEY=your_key_here
US__ALPACA_SECRET_KEY=your_secret_here
US__ALPACA_BASE_URL=https://paper-api.alpaca.markets

# India Market (Angel One)
INDIA__ANGEL_API_KEY=your_key_here
INDIA__ANGEL_CLIENT_ID=your_client_id
INDIA__ANGEL_PIN=your_pin
INDIA__ANGEL_TOTP_SECRET=your_totp_secret

# Alerts (Telegram)
ALERTS__TELEGRAM_BOT_TOKEN=your_bot_token
ALERTS__TELEGRAM_CHAT_ID=your_chat_id
```

### 3. Validate Configuration

```bash
python deployment/scripts/validate_env.py
```

### 4. Build Docker Images

```bash
docker compose -f deployment/docker-compose.yml build
```

### 5. Install Systemd Services

```bash
sudo cp deployment/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
```

### 6. Enable Auto-Start

```bash
sudo systemctl enable aaats-paper-us.service
sudo systemctl enable aaats-paper-india.service
sudo systemctl enable aaats-paper-crypto.service
sudo systemctl enable aaats-dashboard.service
```

### 7. Start Services

```bash
sudo systemctl start aaats-paper-us.service
sudo systemctl start aaats-paper-india.service
sudo systemctl start aaats-paper-crypto.service
sudo systemctl start aaats-dashboard.service
```

### 8. Setup Log Rotation

```bash
sudo cp deployment/logrotate/aaats /etc/logrotate.d/
sudo chmod 644 /etc/logrotate.d/aaats
```

### 9. Setup Automated Backups

```bash
chmod +x deployment/scripts/backup.sh

# Add daily backup cron job (3 AM)
(crontab -l 2>/dev/null; echo "0 3 * * * /home/ubuntu/aaats/deployment/scripts/backup.sh >> /var/log/aaats-backup.log 2>&1") | crontab -
```

---

## Management Commands

### Service Control

```bash
# View status
sudo systemctl status aaats-*

# Start all services
sudo systemctl start aaats-*

# Stop all services
sudo systemctl stop aaats-*

# Restart a service
sudo systemctl restart aaats-paper-us

# View logs (live)
journalctl -u aaats-paper-us -f

# View logs (last 100 lines)
journalctl -u aaats-paper-us -n 100
```

### Docker Commands

```bash
# View running containers
docker ps

# View logs
docker logs aaats-paper-us -f

# Restart container
docker restart aaats-paper-us

# Stop all containers
docker compose -f deployment/docker-compose.yml down

# Start all containers
docker compose -f deployment/docker-compose.yml up -d
```

### Backup & Restore

```bash
# Manual backup
bash deployment/scripts/backup.sh

# List backups
ls -lh /home/ubuntu/aaats-backups/

# Restore from backup
tar -xzf /home/ubuntu/aaats-backups/aaats_backup_YYYYMMDD_HHMMSS.tar.gz -C /home/ubuntu/aaats/
```

---

## Monitoring

### Dashboard Access

```bash
# Get VM IP address
hostname -I

# Access dashboard
http://YOUR_VM_IP:8501
```

### Health Checks

```bash
# Run health check
python scripts/health_check.py

# Check service health
curl http://localhost:8501/_stcore/health
```

### Log Files

```bash
# Application logs
tail -f logs/aaats.log

# Backup logs
tail -f /var/log/aaats-backup.log

# System logs
journalctl -u aaats-* -f
```

---

## Troubleshooting

### Services Won't Start

```bash
# Check service status
sudo systemctl status aaats-paper-us

# Check logs
journalctl -u aaats-paper-us -n 50

# Validate environment
python deployment/scripts/validate_env.py

# Check Docker
docker ps -a
docker logs aaats-paper-us
```

### High Memory Usage

```bash
# Check container stats
docker stats

# Restart services
sudo systemctl restart aaats-*
```

### Dashboard Not Accessible

```bash
# Check if service is running
sudo systemctl status aaats-dashboard

# Check port binding
sudo netstat -tlnp | grep 8501

# Check firewall
sudo ufw status
sudo ufw allow 8501/tcp
```

### Logs Growing Too Large

```bash
# Force log rotation
sudo logrotate -f /etc/logrotate.d/aaats

# Check log sizes
du -sh logs/*
```

---

## Updating AAATS

```bash
# Stop services
sudo systemctl stop aaats-*

# Backup current state
bash deployment/scripts/backup.sh

# Pull latest code
git pull origin main

# Rebuild images
docker compose -f deployment/docker-compose.yml build

# Restart services
sudo systemctl start aaats-*

# Verify
sudo systemctl status aaats-*
```

---

## Uninstalling

```bash
# Stop and disable services
sudo systemctl stop aaats-*
sudo systemctl disable aaats-*

# Remove systemd services
sudo rm /etc/systemd/system/aaats-*.service
sudo systemctl daemon-reload

# Remove Docker containers and images
docker compose -f deployment/docker-compose.yml down
docker rmi $(docker images | grep aaats | awk '{print $3}')

# Remove log rotation
sudo rm /etc/logrotate.d/aaats

# Remove cron job
crontab -l | grep -v "aaats-backup" | crontab -

# Remove application files (optional)
rm -rf /home/ubuntu/aaats
rm -rf /home/ubuntu/aaats-backups
```

---

## Security Notes

1. **Never commit `.env` file** - Contains sensitive API keys
2. **Use paper trading mode** - System is locked to paper trading
3. **Restrict dashboard access** - Use firewall rules or VPN
4. **Regular backups** - Automated daily at 3 AM
5. **Monitor logs** - Check for suspicious activity

---

## Oracle Cloud Free Tier Specs

- **Compute:** 2 AMD cores, 1 GB RAM (Ampere: 4 cores, 24 GB RAM)
- **Storage:** 200 GB block volume
- **Network:** 10 TB/month egress
- **Cost:** $0/month forever

Perfect for running AAATS 24/7!

---

## Support

- **Issues:** https://github.com/Puneethmp/AAATS/issues
- **Documentation:** See main README.md
- **Logs:** Check `logs/` directory and `journalctl`

---

## License

See LICENSE file in repository root.
