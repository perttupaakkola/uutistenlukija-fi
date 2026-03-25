# Ghost CMS — uutistenlukija.fi

Production Ghost 5.x deployment for `cms.uutistenlukija.fi`.

## Stack

| Service | Image | Purpose |
|---------|-------|---------|
| Ghost | `ghost:5-alpine` | CMS + Content API |
| MySQL | `mysql:8.0` | Database (utf8mb4) |
| NGINX | `nginx:1.27-alpine` | Reverse proxy, SSL termination |
| Certbot | `certbot/certbot` | Auto-renewing Let's Encrypt certs |

## Prerequisites

- Ubuntu 22.04+ or Debian 12+ on Hetzner
- DNS A record: `cms.uutistenlukija.fi` → server IP
- DNS records for Mailgun: `mg.uutistenlukija.fi` (SPF, DKIM, MX)
- Ports 80 and 443 open

## Quick Start

```bash
cd ghost/
cp .env.example .env
# Edit .env — fill in all passwords and Mailgun credentials
chmod +x setup.sh
sudo ./setup.sh
```

The setup script handles:
1. Docker + Docker Compose installation (if missing)
2. SSL certificate via certbot (standalone mode)
3. Certbot auto-renewal cron
4. Docker image pull
5. Service startup + health check

## Post-Setup

1. **Create admin account**: Visit `https://cms.uutistenlukija.fi/ghost/`
2. **Configure Mailgun DNS**: Add SPF, DKIM, and MX records for `mg.uutistenlukija.fi`
3. **Test email**: Send a test newsletter from Ghost admin
4. **Stripe** (when available): Uncomment Stripe env vars in `.env`, restart Ghost

## Operations

```bash
# Status
docker compose ps

# Logs
docker logs -f uutistenlukija-ghost

# Restart Ghost only
docker compose restart ghost

# Full restart
docker compose down && docker compose up -d

# Backup database
docker exec uutistenlukija-db mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" ghost > backup_$(date +%Y%m%d).sql

# Update Ghost
docker compose pull ghost
docker compose up -d ghost
```

## Architecture

```
Internet → NGINX (:443) → Ghost (:2368) → MySQL (:3306)
                ↓
         Let's Encrypt
         (auto-renewal)
```

- NGINX handles SSL termination, rate limiting, and static asset caching
- Ghost runs behind NGINX, not exposed directly
- MySQL data persists in Docker volume `db_data`
- Ghost content (images, themes) persists in `ghost_content` volume
- Certbot renews certs automatically (cron + sidecar)

## Security

- Rate limiting on admin panel (5 req/s) and API (10 req/s)
- HSTS enabled (2 year max-age)
- Modern TLS only (1.2+)
- No secrets in code — all via `.env`
- `.env` excluded from git via `.gitignore`

## Mailgun DNS Records

Add these to your DNS for `mg.uutistenlukija.fi`:

| Type | Host | Value |
|------|------|-------|
| TXT | mg.uutistenlukija.fi | `v=spf1 include:mailgun.org ~all` |
| TXT | smtp._domainkey.mg.uutistenlukija.fi | *(from Mailgun dashboard)* |
| MX | mg.uutistenlukija.fi | `mxa.eu.mailgun.org` (priority 10) |
| MX | mg.uutistenlukija.fi | `mxb.eu.mailgun.org` (priority 10) |
| CNAME | email.mg.uutistenlukija.fi | `eu.mailgun.org` |

## Cost

~€40-45/mo total (Ghost hosting on existing Hetzner, Mailgun free tier up to 1000 emails/mo).
