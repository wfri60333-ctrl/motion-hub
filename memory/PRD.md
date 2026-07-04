# MOD_CTRL — Product Requirements Document

## Origin
Discord moderation bot with `/wipe` command evolved into a full Luarmor-clone: Discord bot + FastAPI dashboard for Lua script protection, obfuscation, whitelist keys, HWID locking.

## Personas
- **Script developers** who sell Roblox / executor scripts and need whitelist + obfuscation
- **Server owners** using the moderation half of the bot (`/ban`, `/wipe`, `/purge`, …)

## Core requirements
- 66+ Discord slash commands (moderation + script protection)
- Lua obfuscation with 3 levels (Weak/Medium/Strong) via bundled **Prometheus** obfuscator (requires `lua5.3`)
- Self-hosted whitelist keys with HWID binding
- Loaders (bundles of scripts) with 3 loading modes: menu / bundle / individual
- Discord panel with 5 buttons: Redeem / Get Script / Get Role / Reset HWID / Get Stats
- Dashboard: real-time bot status, logs console, script/loader/key management, audit log
- Deployment on Render via Dockerfile (with lua5.3 installed)

## Implemented (latest session — Jul 2026)
- ✅ Prometheus Lua obfuscator (Weak/Medium/Strong) bundled at `/app/backend/prometheus/`
- ✅ HWID user reset cooldown (24h default) + admin force reset bypass
- ✅ HWID mismatch auto-lockout (5 default) + `/unlockkey` command
- ✅ Per-category role gate (moderation/protection/channel/…) editable from dashboard + `/perms`
- ✅ Unified script/loader dropdown: `/panel` and `/whitelist` accept either type
- ✅ `/whitelist` now grants a role + silent-provisions key (no DM)
- ✅ Discord slash-command AUTOCOMPLETE for target_id and user_key params (live dropdowns)
- ✅ Bulk key generation (`/api/keys/bulk`) + dashboard button downloads a .txt file
- ✅ Kill switch: enable/disable per script (`/api/scripts/{id}/toggle`) + loader
- ✅ Execution cap per key (`max_executions`)
- ✅ Key check API (`/api/checkkey`) — pre-execution metadata
- ✅ HWID event log (`hwid_events` collection) with IP tracking
- ✅ Route ordering: `/api/keys/user/resethwid` before `/api/keys/{id}/resethwid`

## Backlog (P0 first)
- P1: Webhook logs (POST to configurable URL on verify/lockout/reset events)
- P1: Encrypted script backups (versioning)
- P1: Analytics dashboard (executions per day, active keys, geo IPs)
- P2: Ad key system (users earn keys via linkvertise etc.)
- P2: Keyless (FFA) mode
- P2: Runtime variables (script accesses key note/discord_id at runtime via Lua API)

## Test credentials
Bot token + Mongo URL live in `/app/backend/.env`. Discord APP_ID = 1521654504045543578.
