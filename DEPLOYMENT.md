# Railway Deployment Guide

## Quick Start (5 minutes)

### 1. Create GitHub Repo

```bash
cd axle-backend
git init
git add .
git commit -m "Initial Axle backend"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/axle-backend.git
git push -u origin main
```

### 2. Set Up Railway

1. Go to https://railway.app
2. Sign in with GitHub
3. Click **"New Project"**
4. Select **"Deploy from GitHub"**
5. Find and select your `axle-backend` repo
6. Click **"Deploy Now"**

Railway will:
- Auto-detect Python/Flask
- Install dependencies from `requirements.txt`
- Run the `Procfile`

### 3. Add PostgreSQL Database

In Railway dashboard:
1. Click **"Add Service"** (top right)
2. Select **"Database"** → **"PostgreSQL"**
3. Wait for it to start
4. Railway automatically adds `DATABASE_URL` to your app's env

✓ **You're done!** Railway auto-injects the database connection string.

### 4. Verify Deployment

Get your Railway URL from the dashboard, then:

```bash
curl https://<your-project>.up.railway.app/health
# Should return: {"status": "ok"}
```

### 5. Set Environment Variables (Optional)

In Railway dashboard, go to **Variables** and add:

```
SECRET_KEY = <random-string>
FLASK_ENV = production
```

Generate `SECRET_KEY`:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

## Auto-Deploy

Push to GitHub → Railway auto-deploys (1-2 min):

```bash
git add .
git commit -m "Update API endpoint"
git push origin main
```

Check logs in Railway dashboard.

## Local Testing Before Deploy

```bash
# Install
pip install -r requirements.txt

# Create .env
cp .env.example .env
# Edit .env: DATABASE_URL=sqlite:///axle_sync.db (for local testing)

# Run
python app.py
# Go to http://localhost:5000/health
```

## Troubleshooting

**Database connection failed?**
- Check Railway dashboard → PostgreSQL service is running
- Verify `DATABASE_URL` is set in Variables

**Module not found?**
- Add to `requirements.txt` and push

**WebSocket not connecting?**
- Add to client: `const socket = io('https://your-backend.up.railway.app', { transports: ['websocket', 'polling'] });`

## Cost

- **Always Free Tier**: $5 credit/month
  - Small Flask app: ~$2/month
  - PostgreSQL database: ~$1/month
- Fits comfortably in free tier for personal use

## Next: Connect Your Axle Instance

See `integration-example.js` for how to add sync to your UI.
