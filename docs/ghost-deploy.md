# Ghost CMS — Hetzner Deployment Guide

## Prerequisites

- Hetzner Cloud VPS (CX22+ recommended: 2 vCPU, 4GB RAM, 40GB SSD)
- Ubuntu 22.04 LTS
- DNS A record: `cms.uutistenlukija.fi` → server IP
- Mailgun account (EU region) with `mg.uutistenlukija.fi` domain verified
- SSH root access

## Architecture

```
                    ┌──────────────┐
  Internet ──443──▸ │    NGINX     │ ──▸ Ghost (port 2368)
            ──80──▸ │  (SSL term)  │         │
                    └──────────────┘         ▼
                           │            MySQL 8.0
                    Let's Encrypt        (utf8mb4)
                      (certbot)
```

All services run in Docker Compose. NGINX terminates SSL via Let's Encrypt certs.
Certbot sidecar handles auto-renewal.

## Step-by-Step Deployment

### 1. Provision Server

```bash
# Hetzner Cloud console or hcloud CLI
hcloud server create --type cx22 --image ubuntu-22.04 --name ghost-uutistenlukija --location hel1
```

### 2. Initial Server Hardening

```bash
ssh root@<SERVER_IP>

# Updates
apt-get update && apt-get upgrade -y

# Firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable

# (Optional) non-root user
adduser deploy
usermod -aG sudo deploy
```

### 3. Clone and Configure

```bash
cd /opt
git clone <REPO_URL> uutistenlukija
cd uutistenlukija/ghost

# Copy env template and fill in secrets
cp .env.example .env
nano .env
```

Required `.env` values:

| Variable | Example | Notes |
|----------|---------|-------|
| `GHOST_DOMAIN` | `cms.uutistenlukija.fi` | Must match DNS |
| `CERTBOT_EMAIL` | `admin@uutistenlukija.fi` | Let's Encrypt notifications |
| `MYSQL_ROOT_PASSWORD` | (generate: `openssl rand -hex 24`) | MySQL root |
| `MYSQL_GHOST_PASSWORD` | (generate: `openssl rand -hex 24`) | Ghost DB user |
| `MAILGUN_SMTP_USER` | `postmaster@mg.uutistenlukija.fi` | From Mailgun dashboard |
| `MAILGUN_SMTP_PASSWORD` | | From Mailgun dashboard |
| `GHOST_API_URL` | `https://cms.uutistenlukija.fi` | For pipeline integration |
| `GHOST_ADMIN_API_KEY` | | Created after Ghost setup (step 5) |

### 4. Run Setup

```bash
chmod +x setup.sh
sudo ./setup.sh
```

The script will:
1. Install Docker + Docker Compose plugin
2. Install certbot and obtain SSL certificate
3. Pull Docker images (Ghost 5, MySQL 8, NGINX 1.27)
4. Start all services
5. Wait for Ghost health check to pass
6. Print admin URL

### 5. Create Ghost Admin Account

1. Open `https://cms.uutistenlukija.fi/ghost/`
2. Create your admin account (first visitor becomes owner)
3. Go to **Settings → Integrations → Add custom integration**
4. Name it `Pipeline`
5. Copy the **Admin API Key** (format: `id:secret`)
6. Add to `.env` as `GHOST_ADMIN_API_KEY`

### 6. Configure Mailgun DNS

In Mailgun dashboard → Domains → `mg.uutistenlukija.fi`:

```
TXT  mg.uutistenlukija.fi    "v=spf1 include:mailgun.org ~all"
TXT  smtp._domainkey.mg...   (DKIM value from Mailgun)
MX   mg.uutistenlukija.fi    mxa.eu.mailgun.org (priority 10)
MX   mg.uutistenlukija.fi    mxb.eu.mailgun.org (priority 10)
CNAME email.mg...             eu.mailgun.org
```

Send test email from Ghost admin: Settings → Email → Send test email.

### 7. Connect Pipeline

On the pipeline host:

```bash
# Add to pipeline .env
export GHOST_API_URL=https://cms.uutistenlukija.fi
export GHOST_ADMIN_API_KEY=<id:secret from step 5>

# Dry-run test
python3 pipeline/ghost_publisher.py test_article.json --dry-run

# Live test with single article
python3 pipeline/ghost_publisher.py test_article.json
```

## Operations

### Service Management

```bash
cd /opt/uutistenlukija/ghost

# Status
docker compose ps

# Logs
docker logs -f uutistenlukija-ghost
docker logs -f uutistenlukija-db
docker logs -f uutistenlukija-nginx

# Restart
docker compose restart ghost

# Full restart
docker compose down && docker compose up -d
```

### Backup

```bash
# Database dump
docker exec uutistenlukija-db mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" ghost > backup_$(date +%Y%m%d).sql

# Content volume (images, themes)
docker run --rm -v uutistenlukija_ghost_content:/data -v $(pwd):/backup alpine tar czf /backup/ghost_content_$(date +%Y%m%d).tar.gz /data
```

### Ghost Updates

```bash
cd /opt/uutistenlukija/ghost

# Pull latest Ghost 5.x
docker compose pull ghost

# Restart with new image
docker compose up -d ghost

# Check logs for migration output
docker logs -f uutistenlukija-ghost
```

### SSL Certificate Renewal

Handled automatically by the certbot sidecar container + host cron job.
Manual renewal if needed:

```bash
certbot renew --webroot -w /var/www/certbot
docker restart uutistenlukija-nginx
```

## Resource Usage (Expected)

| Service | RAM | Disk |
|---------|-----|------|
| Ghost | ~200-400MB | ~100MB + content |
| MySQL | ~200-400MB | ~50MB + data |
| NGINX | ~10MB | negligible |
| **Total** | **~500-800MB** | **< 1GB base** |

CX22 (4GB RAM) leaves headroom for OS + pipeline processes.

## Monitoring

Ghost health endpoint: `https://cms.uutistenlukija.fi/ghost/api/admin/site/`

Add to `health_check.py`:
```python
# Ghost health check (when GHOST_API_URL is set)
resp = urlopen(f"{GHOST_API_URL}/ghost/api/admin/site/", timeout=10)
if resp.status != 200:
    alerts.append("Ghost CMS unhealthy")
```

## Troubleshooting

| Symptom | Check |
|---------|-------|
| 502 Bad Gateway | `docker logs uutistenlukija-ghost` — Ghost may still be starting |
| SSL error | `certbot certificates` — check expiry; `docker restart uutistenlukija-nginx` |
| DB connection refused | `docker logs uutistenlukija-db` — MySQL may be initializing |
| Mail not sending | Check Mailgun dashboard for bounces; verify DNS records |
| Ghost OOM | Increase memory limit in docker-compose.yml `deploy.resources.limits` |
