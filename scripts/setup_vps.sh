#!/bin/bash
set -e

echo "==============================================="
echo "🚀 GrokSniper AI - VPS Deployment Script"
echo "==============================================="

# Check for root/sudo
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo."
  exit 1
fi

echo "[1/5] Updating system packages..."
apt-get update -y && apt-get upgrade -y
apt-get install -y apt-transport-https ca-certificates curl software-properties-common git jq fail2ban ufw

echo "[2/5] Configuring basic Firewall (UFW)..."
ufw allow OpenSSH
ufw allow 8000/tcp
ufw allow 3000/tcp
echo "y" | ufw enable

echo "[3/5] Installing Docker & Docker Compose..."
if ! command -v docker &> /dev/null; then
  curl -fsSL https://get.docker.com -o get-docker.sh
  sh get-docker.sh
  usermod -aG docker $USER
  rm get-docker.sh
else
  echo "Docker is already installed."
fi

# Docker Compose check (plugin is installed usually with recent script but fallback)
if ! docker compose version &> /dev/null; then
  echo "Docker Compose plugin missing... Installing..."
  apt-get install -y docker-compose-plugin
fi

echo "[4/5] Preparing environment variables..."
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "⚠️ Created .env from .env.example. PLEASE EDIT IT with your API keys now, then re-run this script."
    exit 1
  else
    echo "❌ Missing .env file. Please create it manually."
    exit 1
  fi
fi

echo "[5/5] Building and launching containers..."
docker compose build --no-cache
docker compose up -d

echo "==============================================="
echo "✅ Deployment completed successfully!"
echo "📍 Dashboard: http://<YOUR_VPS_IP>:3000"
echo "⚙️ Backend API: http://<YOUR_VPS_IP>:8000/docs"
echo "📜 To view logs: docker compose logs -f"
echo "==============================================="
