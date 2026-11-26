#!/usr/bin/env bash
# The server keeps the real copy of data/videos.db.
#   ./sync.sh pull   before collecting
#   ./sync.sh push   after export-site (keeps the last 12 server copies in /root/backups/videos-db)
set -euo pipefail
cd "$(dirname "$0")"

HOST=${YTP_SERVER:-vps}
REMOTE_DIR=${YTP_REMOTE_DIR:-/root/Youtube-Popular-Video-Fetcher/data}
SNAPS=/root/backups/videos-db
DB=data/videos.db
LAST_RUN="import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute('select coalesce(max(id),0) from runs').fetchone()[0])"

mkdir -p data
case "${1:-}" in
  pull)
    [ -f "$DB" ] && cp "$DB" "$DB.bak"
    scp -q "$HOST:$REMOTE_DIR/videos.db" "$DB.tmp"
    mv "$DB.tmp" "$DB"
    echo "pulled, last run #$(python3 -c "$LAST_RUN" "$DB")"
    ;;
  push)
    local_run=$(python3 -c "$LAST_RUN" "$DB")
    remote_run=$(ssh "$HOST" "f=$REMOTE_DIR/videos.db; [ -f \$f ] && python3 -c \"$LAST_RUN\" \$f || echo 0")
    if [ "$remote_run" -gt "$local_run" ] && [ "${2:-}" != "--force" ]; then
      echo "server has run #$remote_run, yours is #$local_run. Pull first (or push --force)." >&2
      exit 1
    fi
    # a consistent copy even if the db is open somewhere
    python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" "$DB" "$DB.push"
    ssh "$HOST" "mkdir -p $REMOTE_DIR $SNAPS"
    scp -q "$DB.push" "$HOST:$REMOTE_DIR/videos.db.tmp"
    rm "$DB.push"
    ssh "$HOST" "set -e; cd $REMOTE_DIR
      [ -f videos.db ] && gzip -c videos.db > $SNAPS/videos_\$(date -u +%Y-%m-%d_%H%M%S).db.gz
      mv videos.db.tmp videos.db
      ls -1t $SNAPS/videos_*.db.gz 2>/dev/null | tail -n +13 | xargs -r rm --"
    echo "pushed run #$local_run, server copies: $(ssh "$HOST" "ls $SNAPS | wc -l")"
    ;;
  *)
    echo "usage: $0 pull|push [--force]" >&2
    exit 1
    ;;
esac
