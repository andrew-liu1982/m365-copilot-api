# Quick Reference: Directory Setup

## 🎯 The Essential Rule

**All commands below must run from the PROJECT ROOT directory.**

```
Project root = Where you see:
  ✅ app.py
  ✅ docker-compose.yml
  ✅ README.md
  ✅ copilot/ (directory)
  ✅ server/ (directory)
```

---

## 📍 Current Directory Check

```bash
# Verify you're in the right place
pwd
# Should end with: .../Windows-Copilot-API (or whatever your project is named)

# Or verify by listing files
ls app.py docker-compose.yml  # Should both exist
```

---

## 🔑 One-Time Login Setup

```bash
# Step 1: Go to project root
cd ~/Windows-Copilot-API  # Adjust path to your location

# Step 2: Verify location
pwd  # Check it's correct

# Step 3: Login (creates session/ folder here)
python -m copilot login
# Browser opens → sign in → creates ./session/

# Step 4: Verify session was created
ls session/          # Should see: token.json, profile/
ls session/token.json  # Should exist
```

---

## 🐳 Docker Setup

```bash
# Always start from project root
cd ~/Windows-Copilot-API

# Step 1: Already logged in? (skip if you just did python -m copilot login)
python -m copilot login

# Step 2: Start container (mounts ./session/)
docker compose up

# Step 3: In another terminal, test
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

---

## 🚀 Direct API Server (No Docker)

```bash
# Step 1: Project root
cd ~/Windows-Copilot-API

# Step 2: Login (if not done yet)
python -m copilot login

# Step 3: Start server
COPILOT_MODE=m365 python app.py
# Server listens on http://localhost:8000

# Step 4: Test (in another terminal)
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}]}'
```

---

## ⚠️ Common Mistakes

### ❌ Running from wrong directory

```bash
cd ~/Windows-Copilot-API/copilot
python -m copilot login  # WRONG! session/ created here, not in project root
```

**Fix:** `cd ..` first, then run command from project root.

### ❌ Docker can't find session/

```bash
# You ran login from /tmp directory
cd /tmp
python -m copilot login  # session/ created in /tmp, not in project root

# Docker looks in project root
cd ~/Windows-Copilot-API
docker compose up  # Can't find session/!
```

**Fix:** Login from project root.

### ❌ Path confusion in Docker commands

```bash
# Wrong (absolute path won't work in docker compose)
docker run -v /home/user/session:/app/session ...

# Right (relative path from current directory)
docker run -v $(pwd)/session:/app/session ...
```

---

## 📋 File Structure After Setup

```
~/Windows-Copilot-API/
├── app.py
├── README.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── copilot/
│   ├── __init__.py
│   ├── client.py
│   ├── browser.py
│   └── ...
├── server/
│   ├── __init__.py
│   ├── api.py
│   └── ...
├── session/                    ← Created by python -m copilot login
│   ├── token.json             ← Authentication token
│   └── profile/               ← Browser profile
└── ...other files...
```

---

## 🔍 Troubleshooting: Where's My session/ Folder?

```bash
# Find all session folders (in case you created multiple)
find ~ -name session -type d

# Check if session exists in project root
ls ~/Windows-Copilot-API/session/

# If not found:
cd ~/Windows-Copilot-API
python -m copilot login  # Create it in the correct location
```

---

## 💡 Tips

- **Can't find pwd output?** → In VS Code terminal, type `pwd` and press Enter
- **Verify file existence?** → `test -f ~/Windows-Copilot-API/session/token.json && echo "Found!"`
- **Check working directory?** → Add `pwd` to beginning of scripts: `pwd && python -m copilot login`

---

## Still Confused?

**Remember:** 
1. ✅ Always `cd` to project root first
2. ✅ Run `pwd` to verify
3. ✅ Run `python -m copilot login` from there
4. ✅ `session/` gets created in current directory
5. ✅ Docker/API will find it there
