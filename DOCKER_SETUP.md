# Docker Deployment Guide

## Overview

This project includes Docker support for easy deployment. The key challenge is **authentication**: containers are headless (no browser UI), so the interactive Microsoft sign-in must happen on the **host machine first**.

## Quick Start

### 1. Sign in on the Host (One-time setup)

```bash
# Navigate to the project root directory
# (same directory as app.py, docker-compose.yml, and README.md)
cd /path/to/Windows-Copilot-API
pwd  # Verify: ls app.py docker-compose.yml

# Run the login command from project root
# ⚠️ This is important: session/ will be created in the current directory
python -m copilot login

# This will:
# - Open an interactive browser window
# - Prompt you to sign in with your Microsoft account
# - Save session data to ./session/ (relative to current directory)
# - Create persistent browser profile in ./session/profile/
```

**After completing sign-in:** The `session/` folder (in project root) contains:
- `token.json` — cached access token
- `profile/` — persistent Chromium profile with cookies

### 2. Build and Run Container

```bash
# Build the image
docker build -t copilot-api .

# Run with volume mount (reuses host's session/)
docker run -d \
  -p 8000:8000 \
  -v $(pwd)/session:/app/session \
  -e COPILOT_MODE=m365 \
  -e RATE_LIMIT_RPM=20 \
  copilot-api
```

Or with **docker-compose** (easier):

```bash
docker compose up -d
```

### 3. Test the API

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

---

## Architecture: How Authentication Works

```
PROJECT ROOT (e.g., /home/user/Windows-Copilot-API/)
│
├─ STEP 1: Host Machine (First Time Only)
│  ├─ $ pwd  # Verify you're in project root
│  ├─ $ python -m copilot login  # ⚠️ MUST run from project root
│  ├─ • Opens visible browser
│  ├─ • User signs in with Microsoft account
│  ├─ • Creates ./session/ folder (relative to current directory):
│  │   ├─ token.json (access token + refresh info)
│  │   └─ profile/ (browser profile with cookies)
│  └─ session/ folder ready for container
│
├─ ./session/                     ← Created here by login command
│  ├─ token.json
│  └─ profile/
│
├─ docker-compose.yml            ← References ./session/
├─ app.py
├─ README.md
└─ ...other files...

          ↓
          
├─ STEP 2: Container (Runs Headless)
│  ├─ $ docker run -v $(pwd)/session:/app/session copilot-api
│  ├─ • Mounts ./session/ from project root
│  ├─ • Loads cached token from token.json
│  ├─ • Uses persistent profile for Playwright
│  ├─ • No browser UI needed (runs headless)
│  ├─ • Auto-refreshes token when stale
│  ├─ • Serves API on :8000
│  └─ Ready to receive requests!
```

**Key Point:** The `session/` folder location is relative to where you run `python -m copilot login`. It MUST be in the **project root** for Docker to find it correctly via `$(pwd)/session`.

---

## Configuration

### Environment Variables

Set these in `docker-compose.yml` or with `docker run -e`:

```yaml
COPILOT_MODE: "m365"              # Use M365 Copilot (default: consumer)
RATE_LIMIT_RPM: "20"              # Max requests per minute
RATE_LIMIT_BURST: "6"             # Max burst requests
HOST: "0.0.0.0"                   # Bind to all interfaces
PORT: "8000"                       # API port
```

### Volume Mounts

**Essential:** Mount `session/` to persist authentication

```bash
-v $(pwd)/session:/app/session
```

This ensures:
- Token refresh survives container restarts
- No need to re-login
- Profile cookies are reused

---

## Deployment Scenarios

### Local Development

```bash
# 1. Navigate to project root (where this file is located)
cd /path/to/Windows-Copilot-API
pwd  # Should show: .../Windows-Copilot-API

# 2. Sign in (creates ./session/ in current directory)
python -m copilot login

# 3. Start Docker (will mount ./session/)
docker compose up
```

### VPS / Cloud Server

```bash
# On development machine (in project root)
cd /path/to/Windows-Copilot-API
python -m copilot login  # Creates ./session/
git add session/         # (or scp to server)

# On cloud server (in project root after cloning/copying)
cd /path/to/Windows-Copilot-API
docker compose up
```

**Warning:** `session/` contains credentials. Treat it securely:
- ✅ Use `.gitignore` (already in repo)
- ✅ Encrypt in transit (scp, Git over SSH)
- ❌ Don't commit to public repos
- ❌ Don't expose via HTTP

### Kubernetes (for production scale)

```yaml
# Create a Kubernetes Secret from session files
kubectl create secret generic copilot-session \
  --from-file=session/token.json \
  --from-file=session/profile/

# Mount as volume in Pod
volumeMounts:
  - name: session
    mountPath: /app/session
volumes:
  - name: session
    secret:
      secretName: copilot-session
```

---

## Troubleshooting

### Issue: "Not signed in" error in container

**Cause:** `session/` wasn't created on host  
**Fix:**
```bash
# On host machine
python -m copilot login
# Then restart container
docker compose restart
```

### Issue: Token expired

**Cause:** Token older than 50 minutes  
**Fix:** Container auto-refreshes, but if stuck:
```bash
# Delete cached token
rm session/token.json

# Re-login on host
python -m copilot login

# Restart container
docker compose up --force-recreate
```

### Issue: "Region blocked" error

**Cause:** Anonymous Copilot is geo-restricted  
**Fix:** Ensure you're using signed-in mode:
```bash
COPILOT_MODE=m365  # Use M365, not consumer
```

---

## Security Best Practices

1. **Protect `session/` folder**
   ```bash
   chmod 700 session/
   ```

2. **Never commit to Git**
   ```bash
   # Already in .gitignore, but verify:
   git status  # session/ should not appear
   ```

3. **Use environment variables for sensitive config**
   ```bash
   # Good:
   docker run -e RATE_LIMIT_RPM=20 ...
   
   # Avoid:
   echo "RATE_LIMIT_RPM=20" in Dockerfile
   ```

4. **Use secrets in Kubernetes**
   ```bash
   kubectl create secret generic copilot-session --from-file=session/
   ```

---

## Advanced: Multi-User / Multi-Account

Each account needs a separate session:

```bash
# Account 1
python -m copilot login
mkdir -p sessions/account1
mv session/* sessions/account1/

# Account 2
python -m copilot login
mkdir -p sessions/account2
mv session/* sessions/account2/

# Run separate containers
docker run -v $(pwd)/sessions/account1:/app/session copilot-api
docker run -v $(pwd)/sessions/account2:/app/session copilot-api -p 8001:8000
```

---

## FAQ

**Q: Do I need to re-login after container restart?**  
A: No. The token is cached in `session/token.json` and auto-refreshes.

**Q: Can I move the container to a different machine?**  
A: Yes, copy the `session/` folder. Just ensure network access to Microsoft services.

**Q: What if I don't want to use Docker?**  
A: Run directly on host: `COPILOT_MODE=m365 python app.py`

**Q: Can I deploy to production without exposing credentials?**  
A: Yes, use Kubernetes Secrets or CI/CD secrets:
```bash
kubectl create secret generic copilot-session --from-file=session/
```

---

## Next Steps

- Configure rate limits based on your account's tolerance
- Set up monitoring / logging
- Test with your agents (Opencode, etc.)
- Consider using Kubernetes for scale
