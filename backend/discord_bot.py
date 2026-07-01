"""
Discord Moderation Bot
- Slash command /wipe: deletes every channel in the guild.
- Permission gate: user must have Administrator OR one of the configured roles.
- Posts audit entries to the backend control API.
"""
import os
import sys
import asyncio
import logging
from typing import List

import discord
from discord import app_commands
import httpx

TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
APP_ID_RAW = os.environ.get("DISCORD_APP_ID", "").strip()
ALLOWED_ROLE_IDS: List[int] = []
for r in (os.environ.get("ALLOWED_ROLE_IDS", "") or "").split(","):
    r = r.strip()
    if r.isdigit():
        ALLOWED_ROLE_IDS.append(int(r))

BOT_API_URL = os.environ.get("BOT_API_URL", "http://localhost:8001").rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("bot")


def _log(msg: str):
    print(msg, flush=True)


APP_ID = int(APP_ID_RAW) if APP_ID_RAW.isdigit() else None

intents = discord.Intents.default()
intents.guilds = True
intents.members = False
intents.message_content = False

client = discord.Client(intents=intents, application_id=APP_ID)
tree = app_commands.CommandTree(client)


async def _post_audit(entry: dict):
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            await http.post(f"{BOT_API_URL}/api/bot/audit", json=entry)
    except Exception as e:
        _log(f"[audit] failed: {e}")


async def _push_runtime():
    payload = {
        "ready": client.is_ready(),
        "user": str(client.user) if client.user else None,
        "guild_count": len(client.guilds),
        "latency_ms": round(client.latency * 1000, 1) if client.latency else None,
    }
    try:
        async with httpx.AsyncClient(timeout=5) as http:
            await http.post(f"{BOT_API_URL}/api/bot/runtime", json=payload)
    except Exception as e:
        _log(f"[runtime] failed: {e}")


def _has_permission(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    role_ids = {r.id for r in member.roles}
    return any(rid in role_ids for rid in ALLOWED_ROLE_IDS)


@client.event
async def on_ready():
    _log(f"[ready] logged in as {client.user} ({client.user.id if client.user else '?'})")
    _log(f"[ready] connected to {len(client.guilds)} guild(s)")
    for g in client.guilds:
        _log(f"  - {g.name} ({g.id}) members={g.member_count}")
    try:
        synced = await tree.sync()
        _log(f"[sync] synced {len(synced)} global command(s)")
    except Exception as e:
        _log(f"[sync] failed: {e}")
    await _push_runtime()


@client.event
async def on_guild_join(guild: discord.Guild):
    _log(f"[guild_join] {guild.name} ({guild.id})")
    await _push_runtime()


@client.event
async def on_guild_remove(guild: discord.Guild):
    _log(f"[guild_remove] {guild.name} ({guild.id})")
    await _push_runtime()


# ============ /wipe ============
@tree.command(name="wipe", description="⚠️  Delete EVERY channel in this server. Irreversible.")
@app_commands.describe(confirm='Type "WIPE" (uppercase) to confirm this destructive action.')
async def wipe_cmd(interaction: discord.Interaction, confirm: str):
    if interaction.guild is None:
        await interaction.response.send_message("This command can only be used inside a server.", ephemeral=True)
        return

    member = interaction.user
    if isinstance(member, discord.User):
        member = interaction.guild.get_member(member.id) or member

    if not isinstance(member, discord.Member) or not _has_permission(member):
        await interaction.response.send_message(
            "❌ You do not have permission to use this command.\n"
            "Ask the bot owner to add one of your roles in the dashboard, "
            "or use an account with Administrator permission.",
            ephemeral=True,
        )
        return

    if confirm.strip() != "WIPE":
        await interaction.response.send_message(
            'Confirmation failed. To proceed you must pass exactly `WIPE` (uppercase) as the `confirm` option.',
            ephemeral=True,
        )
        return

    guild = interaction.guild
    channels = list(guild.channels)
    _log(f"[wipe] initiated by {member} ({member.id}) on {guild.name} ({guild.id}) — {len(channels)} channels to remove")

    await interaction.response.send_message(
        f"⚠️  Wiping **{len(channels)}** channels… you'll lose access to this message in a moment.",
        ephemeral=True,
    )

    deleted = 0
    failed = 0
    failed_names: List[str] = []
    for ch in channels:
        try:
            await ch.delete(reason=f"Wipe requested by {member} via /wipe")
            deleted += 1
            _log(f"  ✓ deleted #{ch.name} ({ch.id}) type={ch.type}")
        except Exception as e:
            failed += 1
            failed_names.append(f"{ch.name} ({e.__class__.__name__})")
            _log(f"  ✗ failed to delete #{ch.name}: {e}")

    _log(f"[wipe] complete — deleted={deleted} failed={failed}")

    await _post_audit({
        "guild_id": str(guild.id),
        "guild_name": guild.name,
        "actor_id": str(member.id),
        "actor_name": str(member),
        "action": "wipe_channels",
        "details": {"deleted": deleted, "failed": failed, "failed_names": failed_names[:20]},
    })


async def _heartbeat_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        await _push_runtime()
        await asyncio.sleep(15)


async def main():
    if not TOKEN:
        _log("[fatal] DISCORD_BOT_TOKEN not set")
        sys.exit(2)
    _log(f"[boot] starting Discord bot, app_id={APP_ID}, allowed_role_ids={ALLOWED_ROLE_IDS}")
    async with client:
        asyncio.create_task(_heartbeat_loop())
        await client.start(TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except discord.LoginFailure as e:
        _log(f"[fatal] login failed — invalid bot token: {e}")
        sys.exit(3)
    except KeyboardInterrupt:
        _log("[stop] keyboard interrupt")
    except Exception as e:
        _log(f"[fatal] {type(e).__name__}: {e}")
        raise
