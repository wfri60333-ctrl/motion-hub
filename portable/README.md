# MOD_CTRL — Portable Discord Bot Bundle

This folder is a **standalone**, no-Emergent-needed version of your Discord moderation bot
(with Luarmor integration). Two independent parts:

```
portable/
├── bot/             ← runs 24/7 on bot-hosting.net (or any Python host)
└── dashboard/       ← optional; runs on YOUR PC when you want to browse
```

You do NOT need the dashboard for the bot to work. The dashboard is a nice-to-have UI.

---

## PART 1 — Put the bot online 24/7 (bot-hosting.net)

### Step 1 — Sign up on the free host
Go to **https://bot-hosting.net** → Sign up (no credit card).

### Step 2 — Sign up for a free MongoDB (for /warn, /audit, panel config)
Go to **https://cloud.mongodb.com** → free M0 cluster → copy the "Connection String" (starts
with `mongodb+srv://...`). Whitelist all IPs (`0.0.0.0/0`) in Network Access.

### Step 3 — Upload the bot
From this bundle upload the whole `bot/` folder to bot-hosting.net (or paste the two files
into a new Python bot instance).

### Step 4 — Set these environment variables in bot-hosting.net
| Variable | Value |
| --- | --- |
| `DISCORD_BOT_TOKEN` | your Discord bot token |
| `DISCORD_APP_ID` | `1521654504045543578` |
| `MONGO_URL` | the Atlas connection string from step 2 |
| `DB_NAME` | `modctrl` |
| `STANDALONE` | `1` |
| `LUARMOR_API_KEY` | (only if using Luarmor commands) your Luarmor API key |

### Step 5 — Set start command
```
python discord_bot.py
```

### Step 6 — Deploy → done. Set a phone reminder to hit **Renew** every 4 days.

---

## PART 2 — Dashboard on your PC (optional, free)

The dashboard connects to the **same MongoDB Atlas cluster** as the bot on bot-hosting.net,
so you can see warnings/audit/panel configs from your computer whenever you open it.

### Prerequisites
- Python 3.11+
- Node.js 18+
- Yarn (`npm install -g yarn`)

### Setup (once)
1. Copy your Atlas connection string into `dashboard/backend/.env` (see `.env.example`).
2. In `dashboard/backend/` run: `pip install -r requirements.txt`
3. In `dashboard/frontend/` run: `yarn install`

### Run
- **Windows:** double-click `start-dashboard.bat`
- **Mac / Linux:** run `./start-dashboard.sh`

The script launches both the backend (port 8001) and the frontend (port 3000) and opens
your browser to `http://localhost:3000`.

### Mobile access (same Wi-Fi as your PC)
1. Find your PC's local IP (Windows: `ipconfig` → `IPv4 Address`; Mac: `ifconfig | grep inet`).
2. On your phone browser, open `http://<PC-IP>:3000` while both PC and phone are on the same
   Wi-Fi. That's it.
3. Want mobile access from anywhere? Install **Tailscale** (free) on both devices — instant
   private VPN, no port forwarding.

---

## What if I only want the bot? (skip the dashboard entirely)

Totally fine. The bot is fully self-sufficient. Every slash command works in Discord without
the dashboard. You'll just be missing the fancy control-panel UI.
