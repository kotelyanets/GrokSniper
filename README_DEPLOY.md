# 🚀 GrokSniper AI — Cloud Deployment Guide

Deploy the trading bot on any Linux VPS (Ubuntu 22.04+) for 24/7 operation.

---

## 1. Install Docker on fresh VPS

```bash
# SSH into your server
ssh root@YOUR_SERVER_IP

# Install Docker + Compose
curl -fsSL https://get.docker.com | sh
systemctl enable docker
```

## 2. Upload project files

**Option A — Git (recommended):**
```bash
git clone https://github.com/YOUR_REPO/sniper_bot.git
cd sniper_bot
```

**Option B — SCP from local machine:**
```bash
# Run from your LOCAL machine (Windows PowerShell):
scp -r C:\Users\andko\Desktop\sniper_bot root@YOUR_SERVER_IP:/root/sniper_bot
```

## 3. Configure environment

```bash
cd sniper_bot
cp .env.example .env
nano .env
```

> **⚠️ CRITICAL:** Update `DATABASE_URL` to use the Docker service name instead of `localhost`:
> ```
> DATABASE_URL=postgresql+asyncpg://groksniper_user:YOUR_PASSWORD@postgres:5432/groksniper
> ```
> Also set `BINANCE_TESTNET=False` for live trading.

## 4. Launch the bot

```bash
# Build and start all services (Postgres + Redis + Bot)
docker compose up -d --build

# Verify everything is running
docker compose ps

# Watch live logs
docker compose logs -f sniper-bot
```

## 5. Useful commands

| Command | Description |
|---------|-------------|
| `docker compose logs -f sniper-bot` | Stream bot logs |
| `docker compose restart sniper-bot` | Restart only the bot |
| `docker compose down` | Stop all services |
| `docker compose up -d --build` | Rebuild & restart after code changes |
| `docker compose exec postgres psql -U groksniper_user -d groksniper` | Connect to DB |

## 6. Auto-restart on reboot

Already handled! The `restart: unless-stopped` policy means Docker will automatically restart the bot after a server crash or reboot. Just make sure Docker is enabled:

```bash
systemctl enable docker
```

---

**That's it.** Your bot is now running 24/7 with automatic restarts, log rotation, and a production database. 🎯
