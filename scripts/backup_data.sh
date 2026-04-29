#!/usr/bin/env bash
set -euo pipefail

# Online data backup for automem (SQLite + Qdrant snapshots).
# Safe to run while automem-api and governance-worker are active.
# Output: /root/automem-backups/<timestamp>.tar.gz
# Retention: keep last 14 days locally on VPS.

TS="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="/root/automem-backups/work-${TS}"
OUT_DIR="/root/automem-backups"
OUT="${OUT_DIR}/${TS}.tar.gz"
QDRANT="http://127.0.0.1:6333"
SQLITE_TASKS="/opt/automem/data/tasks/tasks.db"
SQLITE_HISTORY="/opt/automem/data/history/history.db"
RETAIN_DAYS="${BACKUP_RETAIN_DAYS:-14}"

mkdir -p "${WORK}/sqlite" "${WORK}/qdrant"

sqlite_backup () {
  local SRC="$1"
  local DST="$2"
  python3 - "$SRC" "$DST" <<PYEOF
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
PYEOF
}

echo "[1/6] SQLite online backup (tasks.db)"
sqlite_backup "${SQLITE_TASKS}" "${WORK}/sqlite/tasks.db"

echo "[2/6] SQLite online backup (history.db)"
sqlite_backup "${SQLITE_HISTORY}" "${WORK}/sqlite/history.db"

echo "[3/6] Qdrant snapshots"
COLLECTIONS=$(curl -fsS "${QDRANT}/collections" | python3 -c "import json,sys; print(\" \".join(c[\"name\"] for c in json.load(sys.stdin)[\"result\"][\"collections\"]))")
for COLL in ${COLLECTIONS}; do
  echo "  - snapshotting ${COLL}"
  SNAP_NAME=$(curl -fsS -X POST "${QDRANT}/collections/${COLL}/snapshots" | python3 -c "import json,sys; print(json.load(sys.stdin)[\"result\"][\"name\"])")
  echo "  - downloading ${SNAP_NAME}"
  curl -fsS "${QDRANT}/collections/${COLL}/snapshots/${SNAP_NAME}" -o "${WORK}/qdrant/${COLL}.snapshot"
  curl -fsS -X DELETE "${QDRANT}/collections/${COLL}/snapshots/${SNAP_NAME}" > /dev/null
done

echo "[4/6] Capture metadata"
{
  echo "timestamp_utc: ${TS}"
  echo "hostname: $(hostname)"
  echo "automem_git: $(git -C /opt/automem rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "qdrant_collections: ${COLLECTIONS}"
} > "${WORK}/MANIFEST.txt"
cp /opt/automem/backend/.env "${WORK}/backend.env.copy"
chmod 600 "${WORK}/backend.env.copy"

echo "[5/6] Tar + gzip"
tar -C "${WORK}" -czf "${OUT}" .
rm -rf "${WORK}"
chmod 600 "${OUT}"

echo "[6/6] Rotate (keep last ${RETAIN_DAYS} days)"
find "${OUT_DIR}" -maxdepth 1 -name "*.tar.gz" -type f -mtime +${RETAIN_DAYS} -print -delete

ls -lh "${OUT}"
sha256sum "${OUT}"
