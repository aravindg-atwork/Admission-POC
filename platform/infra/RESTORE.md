# Restoring MITRA from backup

Backups run nightly at 02:30 UTC via `mitra-backup.timer`, written by
`/usr/local/bin/mitra-backup.sh`, kept 14 days, logged to
`/var/log/mitra-backup.log`.

    /opt/backups/postgres/platform-<date>.dump      transcripts, review cases,
                                                    published corrections, audit rows
    /opt/backups/qdrant/<collection>-<date>.snapshot  the ingested prospectus corpora

Qdrant is not published on the host, so the script drives it through the API
container (already on that network) and lifts the file out with `docker cp`.
Restores work the same way round.

## Check a backup ran

    tail -20 /var/log/mitra-backup.log
    systemctl list-timers mitra-backup.timer

Lines starting `FAIL` mean that half did not run. A postgres dump under
1 KB is treated as a failure by the script itself.

## Restore Postgres

Never restore over the live database. Restore beside it, look, then swap.

    docker cp /opt/backups/postgres/platform-<date>.dump admission-platform-postgres-1:/tmp/r.dump
    docker exec admission-platform-postgres-1 psql -U platform -c "CREATE DATABASE restored;"
    docker exec admission-platform-postgres-1 pg_restore -U platform -d restored /tmp/r.dump
    docker exec admission-platform-postgres-1 psql -U platform -d restored -c \
      "select relname, n_live_tup from pg_stat_user_tables where n_live_tup>0 order by 2 desc;"

If the row counts look right, stop the API replicas, rename the databases, and
start them again:

    docker stop admission-platform-api-1 admission-platform-api-2
    docker exec admission-platform-postgres-1 psql -U platform -c \
      "ALTER DATABASE platform RENAME TO platform_broken; ALTER DATABASE restored RENAME TO platform;"
    docker start admission-platform-api-1 admission-platform-api-2
    docker exec admission-platform-web-1 nginx -s reload

Keep `platform_broken` until you are sure. Drop it later.

## Restore a Qdrant collection

    docker cp /opt/backups/qdrant/bvsc-<date>.snapshot admission-platform-qdrant-1:/qdrant/snapshots/bvsc.snapshot
    docker exec admission-platform-api-1 python3 -c "import urllib.request as u; \
      r=u.Request('http://qdrant:6333/collections/bvsc/snapshots/recover', \
      data=b'{\"location\":\"file:///qdrant/snapshots/bvsc.snapshot\"}', \
      headers={'Content-Type':'application/json'}, method='PUT'); print(u.urlopen(r).read())"

Then confirm the point count matches what the corpus should hold:

    docker exec admission-platform-api-1 python3 -c "import urllib.request,json; \
      print(json.load(urllib.request.urlopen('http://qdrant:6333/collections/bvsc'))['result']['points_count'])"

Expected: bvsc 192, bfsc 231, btech-dairy 188.

## After any restore

    curl http://127.0.0.1:80/api/readyz          # postgres + redis + qdrant all ok
    curl -X POST http://127.0.0.1:80/api/chat -H 'Content-Type: application/json' \
      -d '{"projectId":"bvsc","question":"What is the first year tuition fee?","conversationState":{"programme":"bvsc"}}'

Redis is deliberately not backed up: it holds the answer cache, rate-limit
counters and provider gates, all of which rebuild themselves. Losing it costs
a slower first few minutes, nothing else.

## The drill

Restoring is proven, not assumed: on 2026-08-22 the day's dump was restored
into a scratch database and returned 7,706 conversation messages against
7,710 live — the difference being test traffic since the dump. Repeat this
monthly. A backup nobody has restored is not a backup.
