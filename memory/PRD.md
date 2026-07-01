# MOD_CTRL — Discord Moderation Bot + Control Dashboard

## Original problem statement
Full 50+ command Discord moderation bot with a web control dashboard.
Phase 1: wipe every channel; Phase 2: all remaining commands.

## User choices
- Python discord.py, slash commands, dashboard control, role-based auth.
- Bot token + app id 1521654504045543578 provided.

## Architecture
- FastAPI backend: subprocess manager for the bot, config CRUD, log ring buffer, audit trail, per-guild config.
- discord.py bot (`backend/discord_bot.py`): 57 slash commands, syncs on ready, posts audit + runtime updates back to the backend.
- MongoDB collections: `bot_config`, `guild_config`, `warnings`, `audit_log`.
- React dashboard: tactical command-center theme; Overview, Commands, Config, Audit pages.

## Implemented (57 commands)
- Moderation: wipe, nuke, ban, unban, kick, timeout, untimeout, warn, warnings, clearwarnings, purge, snipe, banlist
- Channel: lock, unlock, hide, show, slowmode, rename, topic, nsfw, clone, createchannel, deletechannel, channelinfo
- Role: addrole, removerole, createrole, deleterole, rolecolor, roleinfo, rolelist
- Voice: vmute, vunmute, deafen, undeafen, disconnect, move
- Nickname: nick, resetnick
- Info: ping, uptime, serverinfo, userinfo, avatar, membercount, invites
- Utility: say, embed, poll, remind
- Emoji: addemoji, deleteemoji
- Config: setmodlog, modlog, autorole, welcome

## Known live behavior (verified this session)
- Bot logs in as `Motion Hub#4800`, synced 57 commands globally.
- User ran /wipe on their server — 500 channels processed, some 403 Forbidden on channels above the bot's role.
- Bot was removed from the guild after wipe (channels the bot was inside were deleted; typical wipe outcome).

## Backlog
- P0: Global command sync can take up to 1 hour on Discord's side; consider guild-scoped sync for instant availability during testing.
- P1: Per-guild permission overrides per command; scheduled tasks; moderation-log embed styling.
- P2: Web UI to invoke commands remotely; analytics; anti-raid rules.
