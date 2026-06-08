#!/bin/bash

# --- DepthSight "One-Click" Universal Deployer ---
# Supports: Vultr, Contabo, DigitalOcean, and local Linux servers.
# Environment: Ubuntu 22.04+ recommended.

set -e

# Colors for UI
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}------------------------------------------------"
echo "    ____             __  __   _____ _       __    __ "
echo "   / __ \___  ____  / /_/ /_ / ___/(_)___ _/ /_  / /_"
echo "  / / / / _ \/ __ \/ __/ __ \\\\__ \/ / __ \`/ __ \/ __/"
echo " / /_/ /  __/ /_/ / /_/ / / /__/ / / /_/ / / / / /_  "
echo "/_____/\___/ .___/\__/_/ /_/____/_/\__, /_/ /_/\__/  "
echo "          /_/                     /____/             "
echo -e "------------------------------------------------${NC}"

# UI Helpers
spinner() {
    local pid=$1
    local delay=0.1
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  " "$spinstr"
        local spinstr=$temp${spinstr%"$temp"}
        sleep $delay
        printf "\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

run_with_progress() {
    local message=$1
    shift
    echo -n -e "${BLUE}[*] $message...${NC}"
    "$@" > /dev/null 2>&1 &
    spinner $!
    echo -e "${GREEN} DONE!${NC}"
}

# 1. Root Check
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[!] Please run as root (use sudo).${NC}"
  exit 1
fi

# 2. Self-healing (Fix CRLF issues if files were uploaded from Windows)
echo -e "${BLUE}[*] Sanitizing file endings (CRLF -> LF)...${NC}"
# Exclude the running script itself to prevent file offset corruption during execution
find . -type f -name "*.sh" ! -name "$(basename "$0")" -exec sed -i 's/\r$//' {} +
find . -type f -name "Caddyfile" -exec sed -i 's/\r$//' {} +
find . -type f -name ".env*" -exec sed -i 's/\r$//' {} +
find . -type f -name "Dockerfile*" -exec sed -i 's/\r$//' {} +

# 3. Initial System Setup
export DEBIAN_FRONTEND=noninteractive
apt-get update > /dev/null 2>&1
run_with_progress "Updating system packages" apt-get upgrade -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
run_with_progress "Installing base utilities" apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" curl wget git openssl jq ufw

# Setup Swap
if [ ! -f /swapfile ]; then
    run_with_progress "Setting up 4GB swap file" sh -c "fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab"
fi

# Firewall
run_with_progress "Configuring Firewall" sh -c "ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable"

# Docker
if ! [ -x "$(command -v docker)" ]; then
    run_with_progress "Installing Docker Engine" sh -c "curl -fsSL https://get.docker.com | sh"
fi

# 3. Project Setup
if [ -f "deploy.sh" ] && [ -d "api" ]; then
    echo -e "${BLUE}[*] Detected local project files. Skipping clone...${NC}"
    PROJECT_DIR=$(pwd)
else
    PROJECT_DIR="/opt/depthsight"
    if [ ! -d "$PROJECT_DIR/.git" ]; then
        echo -e "${BLUE}[*] Cloning DepthSight repository...${NC}"
        apt-get update && apt-get install -y git
        # If repo is private, you can use: https://TOKEN@github.com/...
        git clone https://github.com/DepthSight-Pro/DepthSight.git "$PROJECT_DIR"
    fi
    cd "$PROJECT_DIR"
fi

# 4. Environment Configuration
if [ ! -f .env ]; then
    echo -e "${BLUE}[*] Generating secure .env configuration...${NC}"
    cp .env.example .env
    
    # Generate random secrets
    JWT_SECRET=$(openssl rand -base64 32)
    CONFIRMATION_SECRET=$(openssl rand -base64 32)
    API_SECRET=$(openssl rand -base64 32)
    FERNET_KEY=$(python3 -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" 2>/dev/null || echo "replace_with_fernet_key")
    
    sed -i "s|JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_SECRET|g" .env
    sed -i "s|CONFIRMATION_SECRET_KEY=.*|CONFIRMATION_SECRET_KEY=$CONFIRMATION_SECRET|g" .env
    sed -i "s|API_KEY_SECRET=.*|API_KEY_SECRET=$API_SECRET|g" .env
    sed -i "s|API_ENCRYPTION_KEY=.*|API_ENCRYPTION_KEY=$FERNET_KEY|g" .env
    
    # Generate unique Redis/Postgres passwords
    POSTGRES_PASS=$(openssl rand -hex 16)
    sed -i "s|POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$POSTGRES_PASS|g" .env
    
    REDIS_BASE_PASS=$(openssl rand -hex 12)
    sed -i "s|REDIS_PASSWORD=.*|REDIS_PASSWORD=$REDIS_BASE_PASS|g" .env
    
    for SVC in API WEBSOCKET BOT CELERY MARKET_DATA; do
        PASS=$(openssl rand -hex 12)
        sed -i "s|REDIS_${SVC}_PASSWORD=.*|REDIS_${SVC}_PASSWORD=$PASS|g" .env
    done
fi

# 5. Smart Networking (IP & Mode Detection)
IP=$(curl -s --max-time 2 https://ifconfig.me || hostname -I | awk '{print $1}')
DOMAIN=""
EMAIL="admin@example.com"
START_BITCART="n"
PROTOCOL="http"

if [ -t 0 ]; then
    echo -e "${BLUE}[?] Are you deploying to a Public Cloud Server (Vultr/Contabo)? (y/N):${NC}"
    read -r IS_PUBLIC
    # Clean input: remove carriage returns, spaces, and convert to lowercase
    IS_PUBLIC=$(echo "$IS_PUBLIC" | tr -d '\r' | xargs | tr '[:upper:]' '[:lower:]')
    echo -e "${BLUE}[*] Debug: Entered value is '$IS_PUBLIC'${NC}"
    
    if [ "$IS_PUBLIC" = "y" ] || [ "$IS_PUBLIC" = "yes" ] || [ "$IS_PUBLIC" = "у" ] || [ "$IS_PUBLIC" = "д" ] || [ "$IS_PUBLIC" = "да" ]; then
        echo -e "${BLUE}[?] Enter your domain (or leave blank for ${IP}.sslip.io):${NC}"
        read -r DOMAIN
        DOMAIN=$(echo "$DOMAIN" | tr -d '\r' | xargs)
        [ -z "$DOMAIN" ] && DOMAIN="${IP}.sslip.io"
        PROTOCOL="https"
        SITE_ADDRESS="$DOMAIN"

        echo -e "${BLUE}[?] Enter your email for SSL alerts (Let's Encrypt):${NC}"
        read -r EMAIL
        EMAIL=$(echo "$EMAIL" | tr -d '\r' | xargs)

        echo -e "${BLUE}[?] Enable Bitcart (Crypto Payments)? (y/N):${NC}"
        read -r START_BITCART
        START_BITCART=$(echo "$START_BITCART" | tr -d '\r' | xargs | tr '[:upper:]' '[:lower:]')
    else
        # Local/Private mode - Fast track
        DOMAIN=$(hostname -I | awk '{print $1}')
        PROTOCOL="http"
        SITE_ADDRESS="http://$DOMAIN"
        echo -e "${GREEN}[+] Local mode detected. System will be available at http://$DOMAIN${NC}"
    fi
else
    # Non-interactive mode (e.g. Vultr Startup Script)
    DOMAIN="${IP}.sslip.io"
    PROTOCOL="https"
    SITE_ADDRESS="$DOMAIN"
fi

# Update .env with networking
sed -i "s|PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=$PROTOCOL://$DOMAIN|g" .env
sed -i "s|VITE_API_URL=.*|VITE_API_URL=$PROTOCOL://$DOMAIN|g" .env
WS_PROTO="ws"
[ "$PROTOCOL" == "https" ] && WS_PROTO="wss"
sed -i "s|VITE_WS_URL=.*|VITE_WS_URL=$WS_PROTO://$DOMAIN/ws|g" .env
CORS_VAL="http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174,http://localhost:8765,http://127.0.0.1:8765,$PROTOCOL://$DOMAIN"
sed -i "/CORS_ORIGINS=/d" .env
echo "CORS_ORIGINS=$CORS_VAL" >> .env

# Force Docker internal names and Production settings
sed -i "s|POSTGRES_HOST=.*|POSTGRES_HOST=postgres|g" .env
sed -i "s|REDIS_HOST=.*|REDIS_HOST=redis|g" .env
sed -i "s|ACTIVE_TRADING_ENVIRONMENT=.*|ACTIVE_TRADING_ENVIRONMENT=mainnet|g" .env
sed -i "s|MARKET_DATA_FANOUT_MODE=.*|MARKET_DATA_FANOUT_MODE=redis|g" .env

# Export for Caddy and other settings
sed -i "/DOMAIN=/d" .env
sed -i "/ADMIN_EMAIL=/d" .env
sed -i "/EMAIL_CONFIRMATION_ENABLED=/d" .env
sed -i "/IS_CENTRAL_HUB=/d" .env
echo "DOMAIN=$SITE_ADDRESS" >> .env
echo "ADMIN_EMAIL=$EMAIL" >> .env
echo "EMAIL_CONFIRMATION_ENABLED=false" >> .env
echo "IS_CENTRAL_HUB=false" >> .env

# 6. Start Engine
COMPOSE_CMD="docker compose"
if [ "$START_BITCART" = "y" ] || [ "$START_BITCART" = "yes" ] || [ "$START_BITCART" = "у" ] || [ "$START_BITCART" = "д" ] || [ "$START_BITCART" = "да" ]; then
    echo -e "${BLUE}[*] Starting DepthSight with Bitcart...${NC}"
    $COMPOSE_CMD -f docker-compose.yml -f docker-compose.bitcart.yml up -d --build
else
    echo -e "${BLUE}[*] Starting DepthSight (Standard)...${NC}"
    $COMPOSE_CMD up -d --build
fi

# Ensure migrations are applied (prevents race conditions of multiple containers running it on start)
echo -e "${BLUE}[*] Running database migrations...${NC}"
# Wait a few seconds for Postgres to be ready just in case
sleep 5
$COMPOSE_CMD exec -T api alembic upgrade head || true

# 7. Setup Auto-Updater Cron Job on Host
echo -e "${BLUE}[*] Configuring host-side cron job for auto-updates...${NC}"
CRON_JOB="* * * * * root if [ -f $PROJECT_DIR/data/.update_trigger ]; then rm $PROJECT_DIR/data/.update_trigger && bash $PROJECT_DIR/update.sh >> $PROJECT_DIR/logs/update.log 2>&1; fi"

if ! grep -q "update_trigger" /etc/crontab; then
    echo "$CRON_JOB" >> /etc/crontab
    # Restart cron daemon to apply changes immediately
    if systemctl is-active --quiet cron; then
        systemctl restart cron
    elif systemctl is-active --quiet crond; then
        systemctl restart crond
    else
        service cron restart >/dev/null 2>&1 || service crond restart >/dev/null 2>&1 || true
    fi
    echo -e "${GREEN}[+] Cron job successfully configured in /etc/crontab${NC}"
else
    echo -e "${GREEN}[+] Cron job already configured in /etc/crontab${NC}"
fi

echo -e "${GREEN}------------------------------------------------"
echo "[+] SUCCESS! DepthSight is rising."
echo "[+] URL: $PROTOCOL://$DOMAIN"
echo "------------------------------------------------${NC}"
