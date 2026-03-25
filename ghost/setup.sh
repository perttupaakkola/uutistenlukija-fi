#!/usr/bin/env bash
# Ghost CMS — One-shot setup script for uutistenlukija.fi
# Run on Hetzner host as root (or with sudo)
#
# Prerequisites:
#   - Ubuntu 22.04+ / Debian 12+
#   - .env file filled in (cp .env.example .env)
#
# Usage:
#   chmod +x setup.sh
#   sudo ./setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOMAIN="${GHOST_DOMAIN:-cms.uutistenlukija.fi}"
EMAIL="${CERTBOT_EMAIL:-admin@uutistenlukija.fi}"

# ── Colors ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1" >&2; exit 1; }

# ── Pre-flight checks ──────────────────────────────────────
[[ $EUID -eq 0 ]] || err "Run as root (sudo ./setup.sh)"
[[ -f "$SCRIPT_DIR/.env" ]] || err ".env file missing. Copy .env.example and fill in secrets."

source "$SCRIPT_DIR/.env"

for var in MYSQL_ROOT_PASSWORD MYSQL_GHOST_PASSWORD MAILGUN_SMTP_USER MAILGUN_SMTP_PASSWORD; do
    [[ -n "${!var:-}" ]] || err "Missing required env var: $var"
done

# ── Step 1: Install Docker if missing ──────────────────────
if ! command -v docker &>/dev/null; then
    log "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
else
    log "Docker already installed ($(docker --version))"
fi

# Ensure docker compose plugin
if ! docker compose version &>/dev/null; then
    log "Installing Docker Compose plugin..."
    apt-get update -qq && apt-get install -y -qq docker-compose-plugin
fi

# ── Step 2: Install certbot if missing ─────────────────────
if ! command -v certbot &>/dev/null; then
    log "Installing certbot..."
    apt-get update -qq && apt-get install -y -qq certbot
else
    log "Certbot already installed"
fi

# ── Step 3: Obtain SSL certificate ────────────────────────
if [[ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]]; then
    log "Obtaining SSL certificate for $DOMAIN..."
    
    # Stop anything on port 80
    if ss -tlnp | grep -q ':80 '; then
        warn "Port 80 in use — attempting standalone certbot anyway"
    fi
    
    certbot certonly \
        --standalone \
        --non-interactive \
        --agree-tos \
        --email "$EMAIL" \
        -d "$DOMAIN" \
        || err "Certbot failed. Ensure DNS A record for $DOMAIN points to this server."
    
    log "SSL certificate obtained"
else
    log "SSL certificate already exists for $DOMAIN"
fi

# ── Step 4: Create certbot webroot dir ─────────────────────
mkdir -p /var/www/certbot

# ── Step 5: Set up certbot auto-renewal cron ───────────────
CRON_CMD="0 3 * * * certbot renew --quiet --deploy-hook 'docker restart uutistenlukija-nginx'"
if ! crontab -l 2>/dev/null | grep -q "certbot renew"; then
    (crontab -l 2>/dev/null; echo "$CRON_CMD") | crontab -
    log "Certbot renewal cron added"
else
    log "Certbot renewal cron already exists"
fi

# ── Step 6: Pull Docker images ─────────────────────────────
log "Pulling Docker images..."
cd "$SCRIPT_DIR"
docker compose pull

# ── Step 7: Start services ─────────────────────────────────
log "Starting Ghost CMS stack..."
docker compose up -d

# ── Step 8: Wait for Ghost to be healthy ───────────────────
log "Waiting for Ghost to start..."
RETRIES=30
for i in $(seq 1 $RETRIES); do
    if docker exec uutistenlukija-ghost wget -qO- http://localhost:2368/ghost/api/admin/site/ &>/dev/null; then
        log "Ghost is healthy!"
        break
    fi
    if [[ $i -eq $RETRIES ]]; then
        err "Ghost failed to start after ${RETRIES} attempts. Check: docker logs uutistenlukija-ghost"
    fi
    sleep 5
done

# ── Step 9: Print summary ──────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Ghost CMS — uutistenlukija.fi"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Admin:   https://$DOMAIN/ghost/"
echo "  Site:    https://$DOMAIN/"
echo "  Status:  docker compose -f $SCRIPT_DIR/docker-compose.yml ps"
echo "  Logs:    docker logs -f uutistenlukija-ghost"
echo ""
echo "  Next steps:"
echo "  1. Visit https://$DOMAIN/ghost/ to create admin account"
echo "  2. Configure Mailgun DNS (SPF/DKIM) for mg.uutistenlukija.fi"
echo "  3. Add Stripe keys when available (Phase 1b)"
echo ""
log "Setup complete."
