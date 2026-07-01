# Render Deployment Tutorial — MOD_CTRL

This gets your backend (FastAPI + loader/verify/keys endpoints) online 24/7 for **free**.

**Time:** ~15 minutes. **Cost:** $0.

---

## Prerequisites (do these first)

1. Your code is on GitHub (use Emergent's "Save to GitHub" button — should already be done).
2. Free MongoDB Atlas account with a connection string ready.
   - https://cloud.mongodb.com → create free M0 cluster
   - Database Access → create user, save password
   - Network Access → add IP `0.0.0.0/0`
   - Connect → Drivers → copy the `mongodb+srv://...` string
3. Your Discord bot token handy.

---

## Step 1 — Push `render.yaml` to your repo

The `render.yaml` at the root of your project pre-configures everything. If you saved this project to GitHub already, make sure the file is committed. It should be here:

```
your-repo/
├── render.yaml            ← this file
├── backend/
│   ├── server.py
│   ├── requirements.txt
│   └── obfuscator.py
└── frontend/
```

If you haven't pushed yet, click **Save to GitHub** in Emergent to push it.

---

## Step 2 — Sign up for Render

1. Go to **https://render.com**
2. Click **Get Started** → **Sign up with GitHub** (easiest)
3. Authorize Render to see your repos

---

## Step 3 — Create Blueprint from your repo

1. In Render dashboard, top-right → **New +** → **Blueprint**
2. Connect your GitHub repo (the one containing MOD_CTRL)
3. Render detects `render.yaml` automatically → **Apply**
4. It'll ask for the 3 secret env variables — paste them:
   - `MONGO_URL` = your Atlas connection string
   - `DISCORD_BOT_TOKEN` = your Discord bot token
   - `LUAOBFUSCATOR_API_KEY` = leave blank if you're using the built-in obfuscator
5. Click **Apply**

Render starts building. Takes 3-5 minutes on first deploy.

---

## Step 4 — Grab your URL

When the build finishes:

1. Click the service **mod-ctrl-backend**
2. At the top you'll see a URL like:
   ```
   https://mod-ctrl-backend-xyz.onrender.com
   ```
3. **Copy that URL** — this is your public API.

4. Test it: open `https://mod-ctrl-backend-xyz.onrender.com/api/` in your browser.
   You should see: `{"service":"discord-bot-control","status":"ok"}`

---

## Step 5 — Point your Discord bot at the Render URL

On bot-hosting.net (where your Discord bot runs), open the bot's environment
variables and add:

```
PUBLIC_API_URL = https://mod-ctrl-backend-xyz.onrender.com
```

Restart the bot on bot-hosting.net.

Now when a user clicks **Get Script** in your `/panel`, the loader snippet uses
your real public Render URL.

---

## Step 6 — Keep Render awake forever (UptimeRobot)

Render free tier sleeps after 15 min of no traffic. Fix it:

1. Sign up free at **https://uptimerobot.com** (no card)
2. **+ Add New Monitor**
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `MOD_CTRL backend`
   - **URL:** `https://mod-ctrl-backend-xyz.onrender.com/api/`
   - **Monitoring Interval:** `5 minutes`
3. **Create Monitor**

Done. UptimeRobot pings your backend every 5 min → Render never sleeps.

---

## Step 7 — Verify everything works end-to-end

1. Open your Render URL in browser + `/api/loaders` → should return `{"loaders":[]}` (empty is fine).
2. In Discord run `/panel Test <script_id> @role` — panel appears.
3. Click **Get Script** on the panel — the loader snippet you get now points to your Render URL.
4. Paste it into a Roblox executor with the correct `script_key` → it should load.

---

## Troubleshooting

**Build fails with "requirements not found"**
→ Make sure `rootDir: backend` in render.yaml matches your repo structure. The `backend/` folder must contain `requirements.txt`.

**"Application failed to respond" on the URL**
→ Check the "Logs" tab in Render. Usually MONGO_URL is wrong or missing.

**Bot in Discord says "no key" but the key IS valid**
→ Bot is still using the old localhost URL. Restart the bot on bot-hosting.net after setting `PUBLIC_API_URL`.

**Render says I hit the 750-hour limit**
→ You have more than one service running on the free tier. Only keep `mod-ctrl-backend` running. The Discord bot is on bot-hosting.net (doesn't count toward Render hours).

---

## Total monthly cost

| Service | Cost | Purpose |
|---|---|---|
| bot-hosting.net | $0 | Discord bot 24/7 |
| Render.com free | $0 | FastAPI backend 24/7 |
| MongoDB Atlas M0 | $0 | Database |
| UptimeRobot | $0 | Keeps Render awake |
| **Total** | **$0** | 100% free stack |
