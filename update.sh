#!/bin/bash

# --- DepthSight Auto-Updater ---
# Pulls latest main, merges new keys from .env.example (without overwriting),
# rebuilds containers and restarts the stack.
# NOTE: DB migrations are NOT run here directly — they run implicitly on
# container boot via ENTRYPOINT ./docker-startup.sh (alembic upgrade head + flock).

set -euo pipefail

# Colors for UI
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}------------------------------------------------"
echo "    ____             __  __   _____ _       __    __ "
echo "   / __ \___  ____  / /_/ /_ / ___/(_)___ _/ /_  / /_"
echo "  / / / / _ \/ __ \/ __/ __ \\\\__ \/ / __ \`/ __ \/ __/"
echo " / /_/ /  __/ /_/ / /_/ / / /__/ / / /_/ / / / / /_  "
echo "/_____/\___/ .___/\__/_/ /_/____/_/\__, /_/ /_/\__/  "
echo "          /_/                     /____/             "
echo -e "------------------------------------------------${NC}"
echo -e "${GREEN}[*] Starting DepthSight Update Process ($(date -u +"%Y-%m-%dT%H:%M:%SZ"))...${NC}"

# 0. Single-instance lock (cron ticks every minute, build takes minutes)
exec 200>/tmp/depthsight-update.lock
if ! flock -n 200; then
    echo -e "${YELLOW}[!] Another update is already running, exiting.${NC}"
    exit 0
fi

# 1. Root Check
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[!] Please run as root (use sudo).${NC}"
  exit 1
fi

# 2. Determine Project Directory (script location first, cron-safe)
SCRIPT_DIR="$(cd "$(dirname "$0")" 2>/dev/null && pwd || echo "")"
if [ -n "${SCRIPT_DIR:-}" ] && [ -f "$SCRIPT_DIR/docker-compose.yml" ] && [ -d "$SCRIPT_DIR/.git" ]; then
    PROJECT_DIR="$SCRIPT_DIR"
elif [ -f "docker-compose.yml" ] && [ -d ".git" ]; then
    PROJECT_DIR="$(pwd)"
else
    PROJECT_DIR="/opt/depthsight"
fi

if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}[!] Project directory not found at $PROJECT_DIR.${NC}"
    exit 1
fi

cd "$PROJECT_DIR"

if [ ! -d ".git" ]; then
    echo -e "${RED}[!] Not a git repository: $PROJECT_DIR (expected docker-compose.yml + .git).${NC}"
    exit 1
fi

# 2a. Status markers for the admin UI (shared data/ volume, see GET /admin/system/update/status).
# The host cron moves .update_trigger -> .update_running before invoking us;
# manual runs may still have the trigger file — consume it here as well.
UPDATE_OK=0
mark_update_failed() {
    if [ "$UPDATE_OK" != "1" ]; then
        date -u +"%Y-%m-%dT%H:%M:%SZ exit=$?" > data/.update_failed 2>/dev/null || true
        rm -f data/.update_running 2>/dev/null || true
    fi
}
trap mark_update_failed EXIT
mkdir -p data logs 2>/dev/null || true
rm -f data/.update_trigger 2>/dev/null || true
date -u +"%Y-%m-%dT%H:%M:%SZ started" > data/.update_running 2>/dev/null || true
# Rotation guard: cron appends every run, keep the log bounded (~5MB tail)
if [ -f logs/update.log ] && [ "$(stat -c%s logs/update.log 2>/dev/null || echo 0)" -gt 5242880 ]; then
    tail -c 5242880 logs/update.log > logs/update.log.tmp 2>/dev/null && mv logs/update.log.tmp logs/update.log || true
fi

# 2b. Pre-flight checks
if [ ! -f ".env" ]; then
    echo -e "${RED}[!] .env not found in $PROJECT_DIR. Run deploy.sh first.${NC}"
    exit 1
fi

if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}[!] Docker daemon is not running. Start docker and retry.${NC}"
    exit 1
fi

# 2c. Backup .env (only .env, no DB dump by design)
BACKUP_FILE=".env.bak-$(date +%Y%m%d-%H%M%S)"
cp .env "$BACKUP_FILE"
echo -e "${GREEN}[+] .env backup saved to $BACKUP_FILE${NC}"
# Retention: keep last 5 backups
ls -t .env.bak-* 2>/dev/null | tail -n +6 | xargs -r rm -f -- || true

# 3. Pull Latest Code (branch is always main)
echo -e "${BLUE}[*] Fetching latest updates from GitHub (main)...${NC}"
if ! git fetch --prune origin main; then
    echo -e "${RED}[!] git fetch origin main failed. Check remote/network.${NC}"
    exit 1
fi
# Reset hard to match the remote (Warning: overwrites local code changes;
# untracked .env / data / logs / gcp_key.json stay intact via .gitignore)
git reset --hard origin/main

# Self-healing CRLF just in case (same mask set as deploy.sh)
find . -type f -name "*.sh" -exec sed -i 's/\r$//' {} + || true
find . -type f -name "Caddyfile" -exec sed -i 's/\r$//' {} + || true
find . -type f -name ".env*" -exec sed -i 's/\r$//' {} + || true
find . -type f -name "Dockerfile*" -exec sed -i 's/\r$//' {} + || true
chmod +x update.sh deploy.sh docker-startup.sh 2>/dev/null || true

if [ ! -f "gcp_key.json" ]; then
    [ -d "gcp_key.json" ] && rm -rf gcp_key.json
    touch gcp_key.json
fi

# 3a. Merge new keys from .env.example without overwriting existing values
if [ -f ".env.example" ]; then
    echo -e "${BLUE}[*] Syncing new keys from .env.example...${NC}"
    ADDED=0
    while IFS= read -r line || [ -n "$line" ]; do
        clean="$(echo "$line" | tr -d '\r')"
        case "$clean" in
            ""|\#*) continue ;;
        esac
        case "$clean" in
            *=*) ;;
            *) continue ;;
        esac
        KEY="${clean%%=*}"
        KEY="$(echo "$KEY" | xargs)"
        case "$KEY" in
            ""|*" "*|*"#"*) continue ;;
        esac
        if ! grep -q "^${KEY}=" .env; then
            # Guarantee trailing newline before append (see deploy.sh append_env)
            if [ -s .env ] && [ -n "$(tail -c 1 .env)" ]; then
                printf '\n' >> .env
            fi
            echo "$clean" >> .env
            echo -e "${GREEN}    + added $KEY${NC}"
            ADDED=$((ADDED + 1))
        fi
    done < .env.example
    echo -e "${GREEN}[+] .env sync done, added $ADDED new key(s).${NC}"
fi

# Ensure bind-mounted dirs exist and are writable by container user (uid 1000)
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/data_storage" "$PROJECT_DIR/logs"
chown -R 1000:1000 "$PROJECT_DIR/data" "$PROJECT_DIR/data_storage" "$PROJECT_DIR/logs" || true

# 4. Rebuild and Restart
echo -e "${BLUE}[*] Rebuilding and restarting containers (this may take a few minutes)...${NC}"

# Determine if Bitcart stack should stay up:
# - explicit flag ENABLE_BITCART=y in .env, OR
# - any existing bitcart container (running or stopped)
USE_BITCART="n"
if [ -f "docker-compose.bitcart.yml" ]; then
    if grep -q "^ENABLE_BITCART=y" .env 2>/dev/null; then
        USE_BITCART="y"
    elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "bitcart"; then
        USE_BITCART="y"
    fi
fi

if [ "$USE_BITCART" = "y" ]; then
    COMPOSE_FILES="-f docker-compose.yml -f docker-compose.bitcart.yml"
else
    COMPOSE_FILES=""
fi

# Pull fresh base images (postgres/redis/caddy/bitcart); non-fatal on failure
# shellcheck disable=SC2086
if ! docker compose $COMPOSE_FILES pull; then
    echo -e "${YELLOW}[!] docker compose pull failed (network/registry?), continuing with local images.${NC}"
fi

# shellcheck disable=SC2086
if [ "$USE_BITCART" = "y" ]; then
    docker compose -f docker-compose.yml -f docker-compose.bitcart.yml up -d --build --remove-orphans
else
    docker compose up -d --build --remove-orphans
fi

# 4a. Post-check: show state + wait briefly for DB health
echo -e "${BLUE}[*] Waiting for postgres/redis health (up to 60s)...${NC}"
for _i in $(seq 1 12); do
    PG_STATUS="$(docker inspect --format '{{.State.Health.Status}}' depthsight_postgres 2>/dev/null || echo "unknown")"
    REDIS_STATUS="$(docker inspect --format '{{.State.Health.Status}}' depthsight_redis 2>/dev/null || echo "unknown")"
    if [ "$PG_STATUS" = "healthy" ] && [ "$REDIS_STATUS" = "healthy" ]; then
        echo -e "${GREEN}[+] postgres + redis healthy.${NC}"
        break
    fi
    if [ "$_i" -eq 12 ]; then
        echo -e "${YELLOW}[!] DB health check timed out (postgres=$PG_STATUS redis=$REDIS_STATUS). Check 'docker compose ps'.${NC}"
    else
        sleep 5
    fi
done

# shellcheck disable=SC2086
docker compose $COMPOSE_FILES ps

# 5. Cleanup (show output instead of silencing; builder cache grows fast on --build)
echo -e "${BLUE}[*] Cleaning up old unused Docker images to free up space...${NC}"
docker image prune -f || echo -e "${YELLOW}[!] docker image prune failed.${NC}"
docker builder prune -f || echo -e "${YELLOW}[!] docker builder prune failed.${NC}"

echo -e "${GREEN}------------------------------------------------"
echo "[+] UPDATE COMPLETE! All services are running the latest version."
echo "------------------------------------------------${NC}"

# Mark success for the admin UI status endpoint (trap becomes a no-op)
UPDATE_OK=1
rm -f data/.update_running data/.update_failed 2>/dev/null || true
date -u +"%Y-%m-%dT%H:%M:%SZ done" > data/.update_done 2>/dev/null || true
trap - EXIT
