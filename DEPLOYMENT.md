# Deployment Guide (Simplified)

This guide covers deploying to your Ubuntu VPS with CloudPanel (MySQL on host) using a single `compose.yml`.

## Prerequisites

1.  **VPS**: Ubuntu with SSH access.
2.  **Software on VPS**: Docker, Docker Compose, Git.
3.  **Database**: MySQL running on VPS `127.0.0.1:3306`.

## 1. One-Time VPS Setup

SSH into your VPS and run these commands:

```bash
# 1. Create app directory
mkdir -p /home/apps/matchb_backend
cd /home/apps/matchb_backend

# 2. Create/Edit .env file
nano .env
```

**Paste this into `.env` (update with REAL values):**

```env
DB_HOST=127.0.0.1
DB_USER=your_db_username
DB_PASSWORD=your_db_password
DB_NAME=your_db_name
DB_PORT=3306
JWT_SECRET=some_super_long_random_string
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_key
CLOUDINARY_API_SECRET=your_secret
APP_URL=http://your-domain.com
```

*Press `Ctrl+X`, then `Y`, then `Enter` to save.*

## 2. GitHub Secrets Setup

In your GitHub Repo > Settings > Secrets > Actions, add:

- `VPS_HOST`: Your VPS IP (e.g., `1.2.3.4`)
- `VPS_USER`: `root` or your username
- `VPS_SSH_KEY`: Your **Private** SSH Key content
- `VPS_PATH`: `/home/apps/matchb_backend`

## 3. How to Deploy

**Option A: Auto-Deploy via GitHub**
Just push your code to the `main` branch.
```bash
git add .
git commit -m "Deploy update"
git push origin main
```
The Action will automatically SSH into your VPS, pull code, and restart Docker.

**Option B: Manual Deployment (SSH)**
If you want to deploy manually from the VPS terminal:

```bash
cd /home/apps/matchb_backend
git pull origin main
docker compose down
docker compose build --no-cache
docker compose up -d
```

## 4. Verification

Check if it's running:
```bash
docker compose ps
docker compose logs -f server
```
