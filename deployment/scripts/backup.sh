#!/bin/bash
# AAATS Automated Backup Script
# Backs up logs, data, and state to timestamped archive

set -e

BACKUP_DIR="/home/ubuntu/aaats-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="aaats_backup_${TIMESTAMP}.tar.gz"
AAATS_DIR="/home/ubuntu/aaats"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

echo "[$(date)] Starting AAATS backup..."

# Create backup archive
tar -czf "${BACKUP_DIR}/${BACKUP_NAME}" \
    -C "$AAATS_DIR" \
    logs/ \
    data/ \
    .env \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='venv/' \
    2>/dev/null || true

# Verify backup was created
if [ -f "${BACKUP_DIR}/${BACKUP_NAME}" ]; then
    BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_NAME}" | cut -f1)
    echo "[$(date)] Backup created: ${BACKUP_NAME} (${BACKUP_SIZE})"
else
    echo "[$(date)] ERROR: Backup failed"
    exit 1
fi

# Keep only last 30 days of backups
find "$BACKUP_DIR" -name "aaats_backup_*.tar.gz" -mtime +30 -delete
echo "[$(date)] Cleaned up backups older than 30 days"

# Count remaining backups
BACKUP_COUNT=$(ls -1 "$BACKUP_DIR"/aaats_backup_*.tar.gz 2>/dev/null | wc -l)
echo "[$(date)] Total backups: ${BACKUP_COUNT}"

echo "[$(date)] Backup complete"
