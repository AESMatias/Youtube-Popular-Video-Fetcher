#!/usr/bin/env bash
# Server deploy: pull, build the static site, serve it with nginx in Docker.
# Cheap to run from cron: it stops early when there is nothing new.
# Usage: ./deploy.sh [--force]    (BRANCH=main ./deploy.sh to pick a branch)

cd "$(dirname "$0")" || exit 1

# cron has a tiny PATH; load nvm if node came from there (nvm.sh breaks under set -u)
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"

set -Eeuo pipefail

PORT=50000
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

log() { echo "$(date '+%F %T') $*"; }
trap 'log "failed at line $LINENO: $BASH_COMMAND"' ERR

# one deploy at a time
exec 9>.deploy.lock
flock -n 9 || { log "another deploy is running"; exit 0; }

BRANCH="${BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
git fetch --quiet origin "$BRANCH"
git reset --hard --quiet "origin/$BRANCH"
HEAD_SHA="$(git rev-parse HEAD)"

if [ "$FORCE" = 0 ] && [ -d dist ] && [ "$(cat .last-deploy 2>/dev/null)" = "$HEAD_SHA" ]; then
    log "nothing to deploy ($BRANCH at ${HEAD_SHA:0:7})"
    exit 0
fi
log "deploying $BRANCH at ${HEAD_SHA:0:7}"

# true when the lock changed or node_modules is missing
if [ package-lock.json -nt node_modules/.package-lock.json ]; then
    log "installing npm dependencies"
    npm ci --no-audit --no-fund
fi

# build aside so a failed build leaves the live dist/ alone
rm -rf dist.new
NODE_OPTIONS=--max-old-space-size=512 npx astro build --outDir dist.new
rm -rf dist.old
[ -d dist ] && mv dist dist.old
mv dist.new dist
rm -rf dist.old

# old setup ran `astro preview` under pm2 on the same port; remove it once
if command -v pm2 >/dev/null && pm2 describe astro-server >/dev/null 2>&1 9>&-; then
    log "removing old pm2 process astro-server"
    pm2 delete astro-server 9>&-
    pm2 save --force 9>&-
fi

if docker compose version >/dev/null 2>&1; then
    compose() { docker compose "$@"; }
else
    compose() { docker-compose "$@"; }
fi
# bind mounts stick to the old dist/ folder after the swap, so recreate the container
compose up -d --force-recreate

for _ in {1..15}; do
    if curl -fsS -o /dev/null "http://127.0.0.1:$PORT/"; then
        echo "$HEAD_SHA" > .last-deploy
        log "ok, site is up on 127.0.0.1:$PORT"
        exit 0
    fi
    sleep 2
done
log "health check failed: http://127.0.0.1:$PORT/ is not answering"
docker logs --tail 30 videos-web || true
exit 1
