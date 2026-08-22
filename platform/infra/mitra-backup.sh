#!/bin/bash
# Nightly backup of everything that cannot be rebuilt from source:
#   postgres - transcripts, review cases, published corrections, audit rows
#   qdrant   - the three ingested prospectus corpora
# Kept 14 days. Restore instructions: /opt/backups/RESTORE.md
set -uo pipefail
STAMP=$(date +%F)
LOG=/var/log/mitra-backup.log
exec >>"$LOG" 2>&1
echo "--- $(date -Is) backup start"

if docker exec admission-platform-postgres-1 pg_dump -U platform -Fc platform > "/opt/backups/postgres/platform-$STAMP.dump"; then
  SIZE=$(stat -c %s "/opt/backups/postgres/platform-$STAMP.dump")
  if [ "$SIZE" -lt 1000 ]; then echo "FAIL postgres dump suspiciously small ($SIZE bytes)"; else echo "ok postgres $SIZE bytes"; fi
else
  echo "FAIL postgres dump"
fi

# Qdrant is NOT published on the host - it exists only on the container
# network - so the API container (already on that network, already has python)
# drives the snapshot, and docker cp lifts the file out of qdrant own volume.
Q() { docker exec admission-platform-api-1 python3 -c "$1" 2>/dev/null; }
COLS=$(Q "import urllib.request,json;print(*[c[\"name\"] for c in json.load(urllib.request.urlopen(\"http://qdrant:6333/collections\"))[\"result\"][\"collections\"]])")
for COL in $COLS; do
  NAME=$(Q "import urllib.request,json;r=urllib.request.Request(\"http://qdrant:6333/collections/$COL/snapshots\",method=\"POST\");print(json.load(urllib.request.urlopen(r))[\"result\"][\"name\"])")
  if [ -n "$NAME" ]; then
    docker cp "admission-platform-qdrant-1:/qdrant/snapshots/$COL/$NAME" "/opt/backups/qdrant/$COL-$STAMP.snapshot" 2>/dev/null \
      && echo "ok qdrant $COL $(stat -c %s /opt/backups/qdrant/$COL-$STAMP.snapshot) bytes" \
      || echo "FAIL qdrant copy $COL"
    Q "import urllib.request;r=urllib.request.Request(\"http://qdrant:6333/collections/$COL/snapshots/$NAME\",method=\"DELETE\");urllib.request.urlopen(r)" >/dev/null
  else
    echo "FAIL qdrant snapshot $COL"
  fi
done

find /opt/backups/postgres -name "*.dump" -mtime +14 -delete
find /opt/backups/qdrant -name "*.snapshot" -mtime +14 -delete
echo "--- $(date -Is) backup end"
