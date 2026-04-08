#!/usr/bin/env bash
# Backs up InfluxDB data to a timestamped directory.
# Requires: running altotrader_influxdb container, INFLUXDB_INIT_ADMIN_TOKEN and
#           INFLUXDB_INIT_ORG set in environment or .env file.
#
# Usage:
#   ./scripts/backup_influxdb.sh
#   BACKUP_DIR=/mnt/backups ./scripts/backup_influxdb.sh
#
# Add to crontab for daily backups at 3am:
#   0 3 * * * cd /path/to/AltoTrader && ./scripts/backup_influxdb.sh >> logs/backup.log 2>&1

set -euo pipefail

# Load .env if present
if [ -f .env ]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' .env | xargs)
fi

TOKEN="${INFLUXDB_INIT_ADMIN_TOKEN:?INFLUXDB_INIT_ADMIN_TOKEN not set}"
ORG="${INFLUXDB_INIT_ORG:?INFLUXDB_INIT_ORG not set}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
DEST="${BACKUP_DIR}/${TIMESTAMP}"

mkdir -p "$DEST"

echo "[$(date)] Starting InfluxDB backup to ${DEST}"

docker exec altotrader_influxdb influx backup \
  --host http://localhost:8086 \
  --token "$TOKEN" \
  --org "$ORG" \
  /tmp/influx_backup

docker cp altotrader_influxdb:/tmp/influx_backup/. "$DEST"
docker exec altotrader_influxdb rm -rf /tmp/influx_backup

echo "[$(date)] Backup complete: ${DEST}"

# Remove backups older than 30 days
find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +30 -exec rm -rf {} + 2>/dev/null || true
echo "[$(date)] Old backups pruned (kept last 30 days)"
