# MOD_CTRL — Discord Moderation Bot + Control Dashboard

## Original problem statement
> i want it to be a whole moderation bot and everything litterly has 50+ commands but the main ones i want is (clear channels like it wipes out every channels in case someone wants to rework there server) but we gonna do the commands after we make a wipe out every channel because i need to rework the server after the clear channels then ima send another mssshae and u work on the commands. secret is dfXwYUC4NMztNy71sKvOYiYucBJsDIvN and application id is 1521654504045543578

## User choices
- Framework: Python `discord.py`
- Command: `/wipe` — deletes ALL channels
- Style: Slash commands
- Web dashboard: yes (start/stop, logs, config)
- Permission: role-based (configurable in dashboard)

## Architecture
- Backend: FastAPI process-manager that launches the bot as a subprocess and streams stdout to an in-memory ring buffer.
- Bot: `backend/discord_bot.py` — discord.py 2.7, one slash command `/wipe`, posts audit entries to backend.
- Frontend: React + Tailwind, Tactical Command Center theme (Chivo / Inter / JetBrains Mono), pages: Overview, Commands, Config, Audit.
- Mongo collections: `bot_config`, `audit_log`.

## Implemented (Phase 1)
- Deploy/Halt bot from dashboard
- Live status (uptime, guild count, latency, ready flag), refreshed every 2.5s
- Live terminal console with pause/follow/clear
- `/wipe` slash command with `confirm: "WIPE"` guard + role/admin gate
- Audit log persisted in Mongo
- Config UI (token, app id, allowed role IDs) + generated invite URL
- Command registry preview (1 active, 7 placeholders)

## Known blocker
- The value the user shared (`dfXwYUC4NMztNy71sKvOYiYucBJsDIvN`) is a **client secret**, not a bot token. Discord rejects it (`Improper token has been passed.`). The user must paste the actual bot token from Developer Portal → Bot → Reset Token in the Config page.

## Prioritized backlog (Phase 2 — after user's next message)
- P0: Grow moderation commands to 50+ (ban, kick, mute, unmute, warn, purge, lockdown, unlock, slowmode, nick, role, mass-role, tempban, softban, timeout, deafen, mute-voice, move-voice, addemoji, deleteemoji, addrole, removerole, giverole, tempmute, embed, say, avatar, userinfo, serverinfo, roleinfo, channelinfo, invites, prune, snipe, unban, banlist, warnings, clearwarnings, note, notes, modlogs, setmodlog, filter, addfilter, removefilter, antispam, antiraid, verify, autorole, welcome)
- P1: Per-guild config, per-command role gates, moderation logs channel binding
- P2: Web UI for issuing commands, analytics, scheduled tasks
