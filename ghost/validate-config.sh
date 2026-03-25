#!/usr/bin/env bash
# Validate Ghost deployment config before running docker-compose up.
# Usage: ./validate-config.sh [.env path]
set -euo pipefail

ENV_FILE="${1:-.env}"
ERRORS=0
WARNINGS=0

red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }

check_var() {
    local var="$1" required="${2:-true}"
    local val="${!var:-}"
    if [ -z "$val" ]; then
        if [ "$required" = "true" ]; then
            red "  ✗ $var — MISSING (required)"
            ((ERRORS++))
        else
            yellow "  ⚠ $var — not set (optional)"
            ((WARNINGS++))
        fi
    else
        # Mask secrets in output
        if [[ "$var" == *KEY* || "$var" == *PASSWORD* || "$var" == *SECRET* ]]; then
            green "  ✓ $var — set (${#val} chars)"
        else
            green "  ✓ $var = $val"
        fi
    fi
}

echo "══════════════════════════════════════════════════════"
echo " Ghost Deployment Config Validator"
echo "══════════════════════════════════════════════════════"
echo ""

# Load .env if it exists
if [ -f "$ENV_FILE" ]; then
    echo "Loading $ENV_FILE..."
    set -a
    source "$ENV_FILE"
    set +a
    echo ""
else
    yellow "No $ENV_FILE found — checking environment variables only"
    echo ""
fi

# ── Required vars ──────────────────────────────────────────
echo "── Ghost Core ──"
check_var GHOST_URL
check_var GHOST_ADMIN_API_KEY
check_var GHOST_DB_PASSWORD

echo ""
echo "── MySQL ──"
check_var MYSQL_ROOT_PASSWORD
check_var MYSQL_DATABASE false
check_var MYSQL_USER false

echo ""
echo "── Mailgun (newsletter delivery) ──"
check_var MAILGUN_SMTP_USER false
check_var MAILGUN_SMTP_PASSWORD false
check_var MAILGUN_DOMAIN false

echo ""
echo "── Stripe (memberships, optional) ──"
check_var STRIPE_SECRET_KEY false
check_var STRIPE_PUBLISHABLE_KEY false

echo ""
echo "── Pipeline Integration ──"
check_var GHOST_API_URL
check_var GHOST_ENABLED false

# ── File checks ────────────────────────────────────────────
echo ""
echo "── Files ──"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

for f in docker-compose.yml nginx.conf config.production.json setup.sh; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        green "  ✓ $f exists"
    else
        red "  ✗ $f — MISSING"
        ((ERRORS++))
    fi
done

# ── Docker check ───────────────────────────────────────────
echo ""
echo "── Runtime ──"
if command -v docker &>/dev/null; then
    green "  ✓ Docker $(docker --version | grep -oP '\d+\.\d+\.\d+')"
else
    red "  ✗ Docker not installed"
    ((ERRORS++))
fi

if command -v docker-compose &>/dev/null || docker compose version &>/dev/null 2>&1; then
    green "  ✓ Docker Compose available"
else
    red "  ✗ Docker Compose not available"
    ((ERRORS++))
fi

if command -v certbot &>/dev/null; then
    green "  ✓ Certbot installed"
else
    yellow "  ⚠ Certbot not installed (needed for SSL)"
    ((WARNINGS++))
fi

# ── URL format check ──────────────────────────────────────
echo ""
echo "── Validation ──"
GHOST_URL="${GHOST_URL:-}"
if [ -n "$GHOST_URL" ]; then
    if [[ "$GHOST_URL" =~ ^https:// ]]; then
        green "  ✓ GHOST_URL uses HTTPS"
    elif [[ "$GHOST_URL" =~ ^http:// ]]; then
        yellow "  ⚠ GHOST_URL uses HTTP (production should use HTTPS)"
        ((WARNINGS++))
    else
        red "  ✗ GHOST_URL invalid format: $GHOST_URL"
        ((ERRORS++))
    fi
fi

GHOST_DB_PASSWORD="${GHOST_DB_PASSWORD:-}"
if [ -n "$GHOST_DB_PASSWORD" ] && [ ${#GHOST_DB_PASSWORD} -lt 12 ]; then
    yellow "  ⚠ GHOST_DB_PASSWORD is short (${#GHOST_DB_PASSWORD} chars, recommend 16+)"
    ((WARNINGS++))
fi

# ── Summary ────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════"
if [ $ERRORS -gt 0 ]; then
    red " FAILED: $ERRORS error(s), $WARNINGS warning(s)"
    echo " Fix required vars before running: docker compose up -d"
    exit 1
elif [ $WARNINGS -gt 0 ]; then
    yellow " PASSED with $WARNINGS warning(s)"
    echo " Review warnings before production deploy."
    exit 0
else
    green " ALL CHECKS PASSED"
    echo " Ready to deploy: cd ghost && docker compose up -d"
    exit 0
fi
