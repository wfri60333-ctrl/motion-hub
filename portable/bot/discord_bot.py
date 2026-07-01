"""
Discord Moderation Bot — MOD_CTRL
50+ slash commands. See COMMAND_LIST in server.py for the full registry.
"""
import os
import sys
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Deque
from collections import defaultdict, deque

import discord
from discord import app_commands
import httpx
from motor.motor_asyncio import AsyncIOMotorClient

# ---------- ENV ----------
TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
APP_ID_RAW = os.environ.get("DISCORD_APP_ID", "").strip()
APP_ID = int(APP_ID_RAW) if APP_ID_RAW.isdigit() else None

ALLOWED_ROLE_IDS: List[int] = []
for r in (os.environ.get("ALLOWED_ROLE_IDS", "") or "").split(","):
    r = r.strip()
    if r.isdigit():
        ALLOWED_ROLE_IDS.append(int(r))

BOT_API_URL = os.environ.get("BOT_API_URL", "http://localhost:8001").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

# When running standalone (on bot-hosting.net etc.), the backend is unreachable
STANDALONE = os.environ.get("STANDALONE", "").lower() in ("1", "true", "yes")

# ---------- LOGGING ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s :: %(message)s")
log = logging.getLogger("bot")


def _log(msg: str):
    print(msg, flush=True)


# ---------- MONGO ----------
mongo = AsyncIOMotorClient(MONGO_URL)
db = mongo[DB_NAME]

# ---------- STATE ----------
STARTED_AT = datetime.now(timezone.utc)
SNIPES: Dict[int, Deque] = defaultdict(lambda: deque(maxlen=5))

intents = discord.Intents.default()
intents.guilds = True
intents.messages = True  # needed for on_message_delete
intents.message_content = False  # privileged; we can live without content on snipe
intents.members = False  # privileged; guarded behind try/except where needed
intents.voice_states = True

client = discord.Client(intents=intents, application_id=APP_ID)
tree = app_commands.CommandTree(client)


# ============= HELPERS =============
async def _post_audit(entry: dict):
    # Always write to Mongo directly (source of truth, works standalone)
    doc = dict(entry)
    import uuid as _uuid
    doc["id"] = str(_uuid.uuid4())
    doc["timestamp"] = datetime.now(timezone.utc).isoformat()
    try:
        await db.audit_log.insert_one(doc)
    except Exception as e:
        _log(f"[audit] mongo insert failed: {e}")
    # Also poke backend if reachable (for live dashboard updates)
    if STANDALONE:
        return
    try:
        async with httpx.AsyncClient(timeout=3) as http:
            await http.post(f"{BOT_API_URL}/api/bot/audit", json=entry)
    except Exception:
        pass


async def _push_runtime():
    if STANDALONE:
        return
    payload = {
        "ready": client.is_ready(),
        "user": str(client.user) if client.user else None,
        "guild_count": len(client.guilds),
        "latency_ms": round(client.latency * 1000, 1) if client.latency else None,
    }
    try:
        async with httpx.AsyncClient(timeout=3) as http:
            await http.post(f"{BOT_API_URL}/api/bot/runtime", json=payload)
    except Exception:
        pass


def _is_authorized(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    role_ids = {r.id for r in getattr(member, "roles", [])}
    return any(rid in role_ids for rid in ALLOWED_ROLE_IDS)


async def _get_modlog_channel(guild: discord.Guild) -> Optional[discord.TextChannel]:
    doc = await db.guild_config.find_one({"guild_id": str(guild.id)}, {"_id": 0})
    if not doc or not doc.get("modlog_channel_id"):
        return None
    try:
        ch = guild.get_channel(int(doc["modlog_channel_id"]))
        if isinstance(ch, discord.TextChannel):
            return ch
    except Exception:
        return None
    return None


async def _modlog(guild: discord.Guild, title: str, description: str, color: int = 0x007AFF,
                  fields: Optional[List[tuple]] = None):
    ch = await _get_modlog_channel(guild)
    if not ch:
        return
    embed = discord.Embed(title=title, description=description, color=color,
                          timestamp=datetime.now(timezone.utc))
    for name, value in (fields or []):
        embed.add_field(name=name, value=value, inline=True)
    try:
        await ch.send(embed=embed)
    except Exception as e:
        _log(f"[modlog] send failed: {e}")


def _human_delta(delta: timedelta) -> str:
    s = int(delta.total_seconds())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def _parse_duration(text: str) -> Optional[timedelta]:
    """Parse strings like '10m', '2h', '1d', '30s' into a timedelta. Returns None if invalid."""
    text = (text or "").strip().lower()
    if not text:
        return None
    unit = text[-1]
    if unit not in "smhd":
        try:
            return timedelta(minutes=int(text))
        except Exception:
            return None
    try:
        n = int(text[:-1])
    except Exception:
        return None
    return {
        "s": timedelta(seconds=n),
        "m": timedelta(minutes=n),
        "h": timedelta(hours=n),
        "d": timedelta(days=n),
    }[unit]


async def _reply(interaction: discord.Interaction, content: str, ephemeral: bool = True,
                 embed: Optional[discord.Embed] = None):
    if interaction.response.is_done():
        await interaction.followup.send(content, embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(content, embed=embed, ephemeral=ephemeral)


def _err(msg: str) -> str:
    return f"❌ {msg}"


def _ok(msg: str) -> str:
    return f"✅ {msg}"


# ============= EVENTS =============
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
async def on_guild_join(guild):
    _log(f"[guild_join] {guild.name} ({guild.id})")
    await _push_runtime()


@client.event
async def on_guild_remove(guild):
    _log(f"[guild_remove] {guild.name} ({guild.id})")
    await _push_runtime()


@client.event
async def on_message_delete(message: discord.Message):
    if message.author and message.author.bot:
        return
    if not message.guild:
        return
    SNIPES[message.channel.id].appendleft({
        "author": str(message.author) if message.author else "unknown",
        "author_id": message.author.id if message.author else 0,
        "content": message.content or "[no content — message intent disabled]",
        "at": datetime.now(timezone.utc).isoformat(),
    })


# ============= CHECKS (app_commands.check pattern) =============
class GuildOnlyFail(app_commands.CheckFailure): pass
class AuthFail(app_commands.CheckFailure): pass


def guild_only():
    async def predicate(interaction: discord.Interaction):
        if interaction.guild is None:
            raise GuildOnlyFail()
        return True
    return app_commands.check(predicate)


def needs_auth():
    async def predicate(interaction: discord.Interaction):
        if interaction.guild is None:
            raise GuildOnlyFail()
        m = interaction.user
        if not isinstance(m, discord.Member):
            m = interaction.guild.get_member(m.id)
        if not m or not _is_authorized(m):
            raise AuthFail()
        return True
    return app_commands.check(predicate)


@tree.error
async def on_app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    try:
        if isinstance(error, GuildOnlyFail):
            await _reply(interaction, _err("This command must be used inside a server."))
        elif isinstance(error, AuthFail):
            await _reply(interaction, _err("You need Administrator or a configured moderator role."))
        else:
            _log(f"[cmd_error] {type(error).__name__}: {error}")
            await _reply(interaction, _err(f"Command error: {error}"))
    except Exception as e:
        _log(f"[cmd_error handler] failed: {e}")


# ============= MODERATION: BANS / KICKS / TIMEOUT =============
@tree.command(name="ban", description="Ban a member from the server.")
@app_commands.describe(user="Member to ban", reason="Reason (shown in audit)",
                       delete_days="Days of messages to delete (0-7)")
@guild_only()
@needs_auth()
async def ban_cmd(interaction: discord.Interaction, user: discord.Member,
                  reason: Optional[str] = None, delete_days: Optional[int] = 0):
    delete_days = max(0, min(7, delete_days or 0))
    try:
        await user.ban(reason=reason or f"Banned by {interaction.user}",
                       delete_message_days=delete_days)
        await _reply(interaction, _ok(f"Banned **{user}** — reason: {reason or 'none'}"), ephemeral=False)
        await _post_audit({
            "guild_id": str(interaction.guild.id), "guild_name": interaction.guild.name,
            "actor_id": str(interaction.user.id), "actor_name": str(interaction.user),
            "action": "ban", "details": {"target_id": str(user.id), "target": str(user), "reason": reason},
        })
        await _modlog(interaction.guild, "Member Banned", f"**{user}** was banned.", 0xFF3B30,
                      fields=[("By", str(interaction.user)), ("Reason", reason or "—")])
    except discord.Forbidden:
        await _reply(interaction, _err("I don't have permission to ban this user."))
    except Exception as e:
        await _reply(interaction, _err(f"Failed to ban: {e}"))


@tree.command(name="unban", description="Unban a user by ID.")
@app_commands.describe(user_id="User ID to unban", reason="Reason")
@guild_only()
@needs_auth()
async def unban_cmd(interaction: discord.Interaction, user_id: str, reason: Optional[str] = None):
    if not user_id.isdigit():
        await _reply(interaction, _err("Invalid user ID."))
        return
    try:
        user = discord.Object(id=int(user_id))
        await interaction.guild.unban(user, reason=reason or f"Unban by {interaction.user}")
        await _reply(interaction, _ok(f"Unbanned user ID `{user_id}`"), ephemeral=False)
        await _modlog(interaction.guild, "Member Unbanned", f"User `{user_id}` unbanned.", 0x34C759,
                      fields=[("By", str(interaction.user)), ("Reason", reason or "—")])
    except discord.NotFound:
        await _reply(interaction, _err("That user is not banned."))
    except Exception as e:
        await _reply(interaction, _err(f"Failed: {e}"))


@tree.command(name="kick", description="Kick a member from the server.")
@app_commands.describe(user="Member to kick", reason="Reason")
@guild_only()
@needs_auth()
async def kick_cmd(interaction: discord.Interaction, user: discord.Member, reason: Optional[str] = None):
    try:
        await user.kick(reason=reason or f"Kicked by {interaction.user}")
        await _reply(interaction, _ok(f"Kicked **{user}** — reason: {reason or 'none'}"), ephemeral=False)
        await _modlog(interaction.guild, "Member Kicked", f"**{user}** was kicked.", 0xFFCC00,
                      fields=[("By", str(interaction.user)), ("Reason", reason or "—")])
    except discord.Forbidden:
        await _reply(interaction, _err("I don't have permission to kick this user."))


@tree.command(name="timeout", description="Timeout (mute) a member for a duration.")
@app_commands.describe(user="Member to timeout", duration="e.g. 10m, 2h, 1d (max 28d)", reason="Reason")
@guild_only()
@needs_auth()
async def timeout_cmd(interaction: discord.Interaction, user: discord.Member,
                      duration: str, reason: Optional[str] = None):
    delta = _parse_duration(duration)
    if not delta or delta.total_seconds() < 1:
        await _reply(interaction, _err("Invalid duration. Use `10m`, `2h`, `1d`, etc."))
        return
    if delta > timedelta(days=28):
        delta = timedelta(days=28)
    try:
        await user.timeout(delta, reason=reason or f"Timeout by {interaction.user}")
        await _reply(interaction, _ok(f"Timed out **{user}** for {_human_delta(delta)}"), ephemeral=False)
        await _modlog(interaction.guild, "Member Timed Out",
                      f"**{user}** for {_human_delta(delta)}", 0xFFCC00,
                      fields=[("By", str(interaction.user)), ("Reason", reason or "—")])
    except discord.Forbidden:
        await _reply(interaction, _err("I don't have permission to timeout this user."))


@tree.command(name="untimeout", description="Remove a timeout from a member.")
@guild_only()
@needs_auth()
async def untimeout_cmd(interaction: discord.Interaction, user: discord.Member):
    try:
        await user.timeout(None, reason=f"Timeout removed by {interaction.user}")
        await _reply(interaction, _ok(f"Removed timeout from **{user}**"), ephemeral=False)
    except discord.Forbidden:
        await _reply(interaction, _err("I don't have permission."))


# ============= WARNINGS =============
@tree.command(name="warn", description="Warn a member (stored in the mod database).")
@app_commands.describe(user="Member to warn", reason="Reason for the warning")
@guild_only()
@needs_auth()
async def warn_cmd(interaction: discord.Interaction, user: discord.Member, reason: str):
    doc = {
        "guild_id": str(interaction.guild.id),
        "user_id": str(user.id),
        "user_name": str(user),
        "actor_id": str(interaction.user.id),
        "actor_name": str(interaction.user),
        "reason": reason,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    await db.warnings.insert_one(doc)
    count = await db.warnings.count_documents({"guild_id": str(interaction.guild.id), "user_id": str(user.id)})
    await _reply(interaction, _ok(f"Warned **{user}** — reason: {reason}\nTotal warnings: **{count}**"),
                 ephemeral=False)
    await _modlog(interaction.guild, "Member Warned", f"**{user}** — {reason}", 0xFFCC00,
                  fields=[("By", str(interaction.user)), ("Total", str(count))])


@tree.command(name="warnings", description="Show all warnings for a member.")
@guild_only()
@needs_auth()
async def warnings_cmd(interaction: discord.Interaction, user: discord.Member):
    cursor = db.warnings.find(
        {"guild_id": str(interaction.guild.id), "user_id": str(user.id)}, {"_id": 0}
    ).sort("at", -1)
    rows = await cursor.to_list(20)
    if not rows:
        await _reply(interaction, _ok(f"**{user}** has no warnings."))
        return
    lines = [f"**{user}** — {len(rows)} warning(s)"]
    for i, w in enumerate(rows, 1):
        ts = w["at"][:19].replace("T", " ")
        lines.append(f"`{i}.` [{ts}] by {w['actor_name']} — {w['reason']}")
    await _reply(interaction, "\n".join(lines))


@tree.command(name="clearwarnings", description="Delete all warnings for a member.")
@guild_only()
@needs_auth()
async def clearwarnings_cmd(interaction: discord.Interaction, user: discord.Member):
    r = await db.warnings.delete_many({"guild_id": str(interaction.guild.id), "user_id": str(user.id)})
    await _reply(interaction, _ok(f"Cleared **{r.deleted_count}** warnings for {user}"), ephemeral=False)


# ============= MESSAGE PURGE =============
@tree.command(name="purge", description="Bulk delete recent messages in this channel.")
@app_commands.describe(amount="How many messages to delete (1-1000)",
                       user="Only delete messages from this user")
@guild_only()
@needs_auth()
async def purge_cmd(interaction: discord.Interaction, amount: int, user: Optional[discord.Member] = None):
    amount = max(1, min(1000, amount))
    if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
        await _reply(interaction, _err("Not a text channel."))
        return
    await interaction.response.defer(ephemeral=True)
    check = (lambda m: m.author.id == user.id) if user else None
    try:
        deleted = await interaction.channel.purge(limit=amount, check=check)
        await interaction.followup.send(_ok(f"Deleted {len(deleted)} messages."), ephemeral=True)
        await _modlog(interaction.guild, "Messages Purged",
                      f"{len(deleted)} in {interaction.channel.mention}", 0xFF3B30,
                      fields=[("By", str(interaction.user)), ("Target", str(user) if user else "any")])
    except Exception as e:
        await interaction.followup.send(_err(f"Failed: {e}"), ephemeral=True)


@tree.command(name="snipe", description="Show the last deleted message in this channel.")
@guild_only()
async def snipe_cmd(interaction: discord.Interaction):
    stack = SNIPES.get(interaction.channel.id)
    if not stack:
        await _reply(interaction, _ok("Nothing to snipe here."))
        return
    s = stack[0]
    e = discord.Embed(description=s["content"], color=0x007AFF,
                      timestamp=datetime.fromisoformat(s["at"]))
    e.set_author(name=s["author"])
    e.set_footer(text=f"in #{interaction.channel.name}")
    await _reply(interaction, "", embed=e, ephemeral=False)


# ============= CHANNEL WIPE / NUKE =============
OWNER_ROLE_NAME = "Owner"


def _has_owner_role(member: discord.Member) -> bool:
    return isinstance(member, discord.Member) and any(
        (r.name or "").lower() == OWNER_ROLE_NAME.lower() for r in member.roles
    )


class WipeConfirmView(discord.ui.View):
    def __init__(self, initiator_id: int, guild_id: int, channel_count: int):
        super().__init__(timeout=120)
        self.initiator_id = initiator_id
        self.guild_id = guild_id
        self.channel_count = channel_count
        self.done = False
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):
        if self.done or not self.message:
            return
        for c in self.children:
            c.disabled = True
        try:
            await self.message.edit(
                content="⌛ **Wipe request timed out.** No action taken.",
                view=self,
            )
        except Exception:
            pass

    @discord.ui.button(label="✓  YES — WIPE EVERYTHING",
                       style=discord.ButtonStyle.danger, custom_id="wipe_confirm_yes")
    async def yes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            await interaction.response.send_message(
                "This request has already been resolved.", ephemeral=True)
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = interaction.guild.get_member(member.id) if interaction.guild else None
        if not member or not _has_owner_role(member):
            # PUBLIC denial
            await interaction.response.send_message(
                f"🚫 {interaction.user.mention} tried to confirm the wipe but does **not** "
                f"hold the **{OWNER_ROLE_NAME}** role. Access denied.",
                ephemeral=False,
            )
            return

        self.done = True
        for c in self.children:
            c.disabled = True
        try:
            await interaction.response.edit_message(
                content=(f"💥 **{interaction.user.mention} confirmed the wipe.**\n"
                         f"Deleting **{self.channel_count}** channels now…"),
                view=self,
            )
        except Exception:
            pass

        guild = interaction.guild
        channels = list(guild.channels)
        _log(f"[wipe] confirmed by {member} ({member.id}) on {guild.name} — {len(channels)} channels")
        deleted, failed = 0, 0
        for ch in channels:
            try:
                await ch.delete(reason=f"Wipe confirmed by {member}")
                deleted += 1
                _log(f"  ✓ deleted #{ch.name}")
            except Exception as e:
                failed += 1
                _log(f"  ✗ failed #{ch.name}: {e}")
        _log(f"[wipe] complete — deleted={deleted} failed={failed}")
        await _post_audit({
            "guild_id": str(guild.id), "guild_name": guild.name,
            "actor_id": str(member.id), "actor_name": str(member),
            "action": "wipe_channels",
            "details": {"deleted": deleted, "failed": failed,
                        "trigger": "button_confirm"},
        })

    @discord.ui.button(label="✕  NO — Cancel",
                       style=discord.ButtonStyle.secondary, custom_id="wipe_confirm_no")
    async def no_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            await interaction.response.send_message(
                "This request has already been resolved.", ephemeral=True)
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = interaction.guild.get_member(member.id) if interaction.guild else None
        if not member or not _has_owner_role(member):
            await interaction.response.send_message(
                f"🚫 {interaction.user.mention} tried to cancel the wipe but does **not** "
                f"hold the **{OWNER_ROLE_NAME}** role. Only the Owner can decide.",
                ephemeral=False,
            )
            return

        self.done = True
        for c in self.children:
            c.disabled = True
        await interaction.response.edit_message(
            content=f"✅ **Wipe canceled** by {interaction.user.mention}.",
            view=self,
        )


@tree.command(name="wipe",
              description="⚠️  Public confirmation to delete EVERY channel. Owner role only.")
@guild_only()
@needs_auth()
async def wipe_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    channels = list(guild.channels)
    view = WipeConfirmView(interaction.user.id, guild.id, len(channels))
    content = (
        f"⚠️  **SERVER WIPE REQUESTED** — by {interaction.user.mention}\n"
        f"This will delete **{len(channels)}** channels in **{guild.name}**. "
        f"This action is **irreversible**.\n\n"
        f"🔒 Only a member with the **{OWNER_ROLE_NAME}** role can confirm or cancel. "
        f"Anyone else who clicks will be publicly denied.\n"
        f"⌛ Request auto-expires in 2 minutes."
    )
    # PUBLIC — everyone in the channel sees this
    await interaction.response.send_message(content=content, view=view, ephemeral=False)
    try:
        view.message = await interaction.original_response()
    except Exception:
        pass
    _log(f"[wipe] request opened by {interaction.user} on {guild.name} "
         f"({len(channels)} channels) — awaiting Owner confirmation")


@tree.command(name="nuke", description="Clone this channel and delete the original (wipes messages).")
@guild_only()
@needs_auth()
async def nuke_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel):
        await _reply(interaction, _err("Only text channels can be nuked."))
        return
    await interaction.response.send_message("💥 Nuking channel…", ephemeral=True)
    try:
        pos = ch.position
        new_ch = await ch.clone(reason=f"Nuke by {interaction.user}")
        await new_ch.edit(position=pos)
        await ch.delete(reason=f"Nuke by {interaction.user}")
        await new_ch.send(f"💥 Channel nuked by **{interaction.user}**")
        await _post_audit({
            "guild_id": str(interaction.guild.id), "guild_name": interaction.guild.name,
            "actor_id": str(interaction.user.id), "actor_name": str(interaction.user),
            "action": "nuke_channel", "details": {"channel": ch.name},
        })
    except Exception as e:
        _log(f"[nuke] failed: {e}")


# ============= CHANNEL MANAGEMENT =============
@tree.command(name="lock", description="Lock this channel (deny @everyone from sending).")
@guild_only()
@needs_auth()
async def lock_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel):
        await _reply(interaction, _err("Not a text channel."))
        return
    ow = ch.overwrites_for(interaction.guild.default_role)
    ow.send_messages = False
    await ch.set_permissions(interaction.guild.default_role, overwrite=ow,
                             reason=f"Lock by {interaction.user}")
    await _reply(interaction, _ok(f"🔒 Locked {ch.mention}"), ephemeral=False)


@tree.command(name="unlock", description="Unlock this channel.")
@guild_only()
@needs_auth()
async def unlock_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    if not isinstance(ch, discord.TextChannel):
        await _reply(interaction, _err("Not a text channel."))
        return
    ow = ch.overwrites_for(interaction.guild.default_role)
    ow.send_messages = None
    await ch.set_permissions(interaction.guild.default_role, overwrite=ow,
                             reason=f"Unlock by {interaction.user}")
    await _reply(interaction, _ok(f"🔓 Unlocked {ch.mention}"), ephemeral=False)


@tree.command(name="hide", description="Hide this channel from @everyone.")
@guild_only()
@needs_auth()
async def hide_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    ow = ch.overwrites_for(interaction.guild.default_role)
    ow.view_channel = False
    await ch.set_permissions(interaction.guild.default_role, overwrite=ow)
    await _reply(interaction, _ok(f"Channel hidden."))


@tree.command(name="show", description="Reveal this channel to @everyone.")
@guild_only()
@needs_auth()
async def show_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    ow = ch.overwrites_for(interaction.guild.default_role)
    ow.view_channel = None
    await ch.set_permissions(interaction.guild.default_role, overwrite=ow)
    await _reply(interaction, _ok(f"Channel visible."))


@tree.command(name="slowmode", description="Set channel slowmode (seconds; 0 disables).")
@guild_only()
@needs_auth()
async def slowmode_cmd(interaction: discord.Interaction, seconds: int):
    seconds = max(0, min(21600, seconds))
    if not isinstance(interaction.channel, discord.TextChannel):
        await _reply(interaction, _err("Not a text channel."))
        return
    await interaction.channel.edit(slowmode_delay=seconds)
    await _reply(interaction, _ok(f"Slowmode set to {seconds}s."), ephemeral=False)


@tree.command(name="rename", description="Rename this channel.")
@guild_only()
@needs_auth()
async def rename_cmd(interaction: discord.Interaction, new_name: str):
    await interaction.channel.edit(name=new_name, reason=f"Rename by {interaction.user}")
    await _reply(interaction, _ok(f"Renamed to `{new_name}`"), ephemeral=False)


@tree.command(name="topic", description="Set the topic of this channel.")
@guild_only()
@needs_auth()
async def topic_cmd(interaction: discord.Interaction, text: str):
    if not isinstance(interaction.channel, discord.TextChannel):
        await _reply(interaction, _err("Not a text channel."))
        return
    await interaction.channel.edit(topic=text)
    await _reply(interaction, _ok("Topic updated."))


@tree.command(name="nsfw", description="Toggle NSFW on this channel.")
@guild_only()
@needs_auth()
async def nsfw_cmd(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel):
        await _reply(interaction, _err("Not a text channel."))
        return
    new = not interaction.channel.is_nsfw()
    await interaction.channel.edit(nsfw=new)
    await _reply(interaction, _ok(f"NSFW set to {new}."))


@tree.command(name="clone", description="Clone this channel (preserves permissions).")
@guild_only()
@needs_auth()
async def clone_cmd(interaction: discord.Interaction):
    new_ch = await interaction.channel.clone(reason=f"Clone by {interaction.user}")
    await _reply(interaction, _ok(f"Cloned to {new_ch.mention}"))


@tree.command(name="createchannel", description="Create a new text channel.")
@guild_only()
@needs_auth()
async def createchannel_cmd(interaction: discord.Interaction, name: str,
                            category: Optional[discord.CategoryChannel] = None):
    ch = await interaction.guild.create_text_channel(name=name, category=category,
                                                     reason=f"Create by {interaction.user}")
    await _reply(interaction, _ok(f"Created {ch.mention}"))


@tree.command(name="deletechannel", description="Delete a channel.")
@guild_only()
@needs_auth()
async def deletechannel_cmd(interaction: discord.Interaction, channel: discord.abc.GuildChannel):
    name = channel.name
    await channel.delete(reason=f"Delete by {interaction.user}")
    await _reply(interaction, _ok(f"Deleted `#{name}`"))


# ============= ROLE MANAGEMENT =============
@tree.command(name="addrole", description="Add a role to a member.")
@guild_only()
@needs_auth()
async def addrole_cmd(interaction: discord.Interaction, user: discord.Member, role: discord.Role):
    try:
        await user.add_roles(role, reason=f"By {interaction.user}")
        await _reply(interaction, _ok(f"Added {role.mention} to {user.mention}"), ephemeral=False)
    except discord.Forbidden:
        await _reply(interaction, _err("Missing permission or role hierarchy."))


@tree.command(name="removerole", description="Remove a role from a member.")
@guild_only()
@needs_auth()
async def removerole_cmd(interaction: discord.Interaction, user: discord.Member, role: discord.Role):
    try:
        await user.remove_roles(role, reason=f"By {interaction.user}")
        await _reply(interaction, _ok(f"Removed {role.mention} from {user.mention}"), ephemeral=False)
    except discord.Forbidden:
        await _reply(interaction, _err("Missing permission or role hierarchy."))


@tree.command(name="createrole", description="Create a new role.")
@guild_only()
@needs_auth()
async def createrole_cmd(interaction: discord.Interaction, name: str, color: Optional[str] = None):
    kwargs = {"name": name, "reason": f"By {interaction.user}"}
    if color:
        try:
            kwargs["colour"] = discord.Colour(int(color.lstrip("#"), 16))
        except Exception:
            pass
    role = await interaction.guild.create_role(**kwargs)
    await _reply(interaction, _ok(f"Created {role.mention}"))


@tree.command(name="deleterole", description="Delete a role.")
@guild_only()
@needs_auth()
async def deleterole_cmd(interaction: discord.Interaction, role: discord.Role):
    name = role.name
    await role.delete(reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Deleted role `@{name}`"))


@tree.command(name="rolecolor", description="Change a role's color (hex like #FF3B30).")
@guild_only()
@needs_auth()
async def rolecolor_cmd(interaction: discord.Interaction, role: discord.Role, color: str):
    try:
        c = discord.Colour(int(color.lstrip("#"), 16))
    except Exception:
        await _reply(interaction, _err("Invalid hex color."))
        return
    await role.edit(colour=c)
    await _reply(interaction, _ok(f"{role.mention} recolored."))


@tree.command(name="roleinfo", description="Show information about a role.")
@guild_only()
async def roleinfo_cmd(interaction: discord.Interaction, role: discord.Role):
    e = discord.Embed(title=f"Role: {role.name}", color=role.colour)
    e.add_field(name="ID", value=str(role.id))
    e.add_field(name="Members", value=str(len(role.members)))
    e.add_field(name="Color", value=str(role.colour))
    e.add_field(name="Hoisted", value=str(role.hoist))
    e.add_field(name="Mentionable", value=str(role.mentionable))
    e.add_field(name="Position", value=str(role.position))
    e.add_field(name="Created", value=role.created_at.strftime("%Y-%m-%d"))
    await _reply(interaction, "", embed=e, ephemeral=False)


@tree.command(name="rolelist", description="List all roles in this server.")
@guild_only()
async def rolelist_cmd(interaction: discord.Interaction):
    roles = sorted(interaction.guild.roles, key=lambda r: -r.position)
    lines = [f"`{i:>2}` {r.mention} — `{r.id}`" for i, r in enumerate(roles) if r.name != "@everyone"]
    text = "\n".join(lines) or "(no roles)"
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    e = discord.Embed(title=f"Roles ({len(roles)-1})", description=text, color=0x007AFF)
    await _reply(interaction, "", embed=e)


# ============= NICKNAME =============
@tree.command(name="nick", description="Change a member's nickname.")
@guild_only()
@needs_auth()
async def nick_cmd(interaction: discord.Interaction, user: discord.Member, nickname: str):
    await user.edit(nick=nickname, reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Nickname set for {user.mention}"), ephemeral=False)


@tree.command(name="resetnick", description="Reset a member's nickname.")
@guild_only()
@needs_auth()
async def resetnick_cmd(interaction: discord.Interaction, user: discord.Member):
    await user.edit(nick=None, reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Nickname reset for {user.mention}"), ephemeral=False)


# ============= VOICE =============
@tree.command(name="vmute", description="Server-mute a member in voice.")
@guild_only()
@needs_auth()
async def vmute_cmd(interaction: discord.Interaction, user: discord.Member):
    await user.edit(mute=True, reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Voice-muted {user.mention}"), ephemeral=False)


@tree.command(name="vunmute", description="Un-mute a member in voice.")
@guild_only()
@needs_auth()
async def vunmute_cmd(interaction: discord.Interaction, user: discord.Member):
    await user.edit(mute=False, reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Voice-unmuted {user.mention}"), ephemeral=False)


@tree.command(name="deafen", description="Server-deafen a member in voice.")
@guild_only()
@needs_auth()
async def deafen_cmd(interaction: discord.Interaction, user: discord.Member):
    await user.edit(deafen=True, reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Deafened {user.mention}"), ephemeral=False)


@tree.command(name="undeafen", description="Un-deafen a member in voice.")
@guild_only()
@needs_auth()
async def undeafen_cmd(interaction: discord.Interaction, user: discord.Member):
    await user.edit(deafen=False, reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Un-deafened {user.mention}"), ephemeral=False)


@tree.command(name="disconnect", description="Disconnect a member from voice.")
@guild_only()
@needs_auth()
async def disconnect_cmd(interaction: discord.Interaction, user: discord.Member):
    if not user.voice or not user.voice.channel:
        await _reply(interaction, _err("Member is not in a voice channel."))
        return
    await user.move_to(None, reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Disconnected {user.mention}"), ephemeral=False)


@tree.command(name="move", description="Move a member to another voice channel.")
@guild_only()
@needs_auth()
async def move_cmd(interaction: discord.Interaction, user: discord.Member,
                   channel: discord.VoiceChannel):
    if not user.voice or not user.voice.channel:
        await _reply(interaction, _err("Member is not in a voice channel."))
        return
    await user.move_to(channel, reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Moved {user.mention} → {channel.mention}"), ephemeral=False)


# ============= INFO =============
@tree.command(name="ping", description="Show bot gateway latency.")
async def ping_cmd(interaction: discord.Interaction):
    await _reply(interaction, f"🏓 **{round(client.latency*1000)}ms**", ephemeral=False)


@tree.command(name="uptime", description="Show bot uptime.")
async def uptime_cmd(interaction: discord.Interaction):
    await _reply(interaction, f"⏱ Uptime: **{_human_delta(datetime.now(timezone.utc) - STARTED_AT)}**",
                 ephemeral=False)


@tree.command(name="serverinfo", description="Show information about this server.")
@guild_only()
async def serverinfo_cmd(interaction: discord.Interaction):
    g = interaction.guild
    e = discord.Embed(title=g.name, color=0x007AFF, timestamp=g.created_at)
    if g.icon: e.set_thumbnail(url=g.icon.url)
    e.add_field(name="ID", value=str(g.id))
    e.add_field(name="Owner", value=str(g.owner))
    e.add_field(name="Members", value=str(g.member_count))
    e.add_field(name="Channels", value=str(len(g.channels)))
    e.add_field(name="Roles", value=str(len(g.roles)))
    e.add_field(name="Boosts", value=str(g.premium_subscription_count))
    e.set_footer(text="Created")
    await _reply(interaction, "", embed=e, ephemeral=False)


@tree.command(name="userinfo", description="Show information about a member.")
@guild_only()
async def userinfo_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    u = user or interaction.user
    e = discord.Embed(title=str(u), color=0x007AFF, timestamp=u.created_at)
    if u.display_avatar: e.set_thumbnail(url=u.display_avatar.url)
    e.add_field(name="ID", value=str(u.id))
    if isinstance(u, discord.Member):
        e.add_field(name="Nickname", value=u.nick or "—")
        e.add_field(name="Joined", value=u.joined_at.strftime("%Y-%m-%d") if u.joined_at else "—")
        e.add_field(name="Top Role", value=u.top_role.mention if u.top_role else "—")
        e.add_field(name="Bot", value=str(u.bot))
    e.set_footer(text="Account created")
    await _reply(interaction, "", embed=e, ephemeral=False)


@tree.command(name="avatar", description="Show a user's avatar.")
async def avatar_cmd(interaction: discord.Interaction, user: Optional[discord.User] = None):
    u = user or interaction.user
    e = discord.Embed(title=f"{u}'s avatar", color=0x007AFF)
    if u.display_avatar: e.set_image(url=u.display_avatar.url)
    await _reply(interaction, "", embed=e, ephemeral=False)


@tree.command(name="membercount", description="Total members in this server.")
@guild_only()
async def membercount_cmd(interaction: discord.Interaction):
    await _reply(interaction, f"👥 **{interaction.guild.member_count}** members",
                 ephemeral=False)


@tree.command(name="channelinfo", description="Show information about the current channel.")
@guild_only()
async def channelinfo_cmd(interaction: discord.Interaction):
    ch = interaction.channel
    e = discord.Embed(title=f"#{ch.name}", color=0x007AFF)
    e.add_field(name="ID", value=str(ch.id))
    e.add_field(name="Type", value=str(ch.type))
    e.add_field(name="Category", value=ch.category.name if ch.category else "—")
    if isinstance(ch, discord.TextChannel):
        e.add_field(name="NSFW", value=str(ch.is_nsfw()))
        e.add_field(name="Slowmode", value=f"{ch.slowmode_delay}s")
        e.add_field(name="Topic", value=ch.topic or "—", inline=False)
    e.add_field(name="Created", value=ch.created_at.strftime("%Y-%m-%d"))
    await _reply(interaction, "", embed=e, ephemeral=False)


@tree.command(name="banlist", description="Show up to 20 recent bans.")
@guild_only()
@needs_auth()
async def banlist_cmd(interaction: discord.Interaction):
    bans = []
    async for b in interaction.guild.bans(limit=20):
        bans.append(f"• `{b.user.id}` — {b.user} ({b.reason or 'no reason'})")
    text = "\n".join(bans) or "(no bans)"
    await _reply(interaction, text)


@tree.command(name="invites", description="Show active guild invites.")
@guild_only()
@needs_auth()
async def invites_cmd(interaction: discord.Interaction):
    try:
        invs = await interaction.guild.invites()
    except discord.Forbidden:
        await _reply(interaction, _err("Missing Manage Server permission."))
        return
    lines = [f"• `{i.code}` — uses: {i.uses}, by {i.inviter}" for i in invs[:20]]
    await _reply(interaction, "\n".join(lines) or "(no invites)")


# ============= UTILITY =============
@tree.command(name="say", description="Have the bot say something in this channel.")
@guild_only()
@needs_auth()
async def say_cmd(interaction: discord.Interaction, message: str):
    await interaction.channel.send(message)
    await _reply(interaction, _ok("Sent."))


@tree.command(name="embed", description="Post an embed in this channel.")
@guild_only()
@needs_auth()
async def embed_cmd(interaction: discord.Interaction, title: str, description: str,
                    color: Optional[str] = "#007AFF"):
    try:
        c = discord.Colour(int((color or "#007AFF").lstrip("#"), 16))
    except Exception:
        c = discord.Colour(0x007AFF)
    e = discord.Embed(title=title, description=description, color=c)
    await interaction.channel.send(embed=e)
    await _reply(interaction, _ok("Embed sent."))


@tree.command(name="poll", description="Create a simple yes/no poll.")
@guild_only()
async def poll_cmd(interaction: discord.Interaction, question: str):
    msg = await interaction.channel.send(f"📊 **Poll:** {question}\n_by {interaction.user.mention}_")
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    await _reply(interaction, _ok("Poll posted."))


@tree.command(name="remind", description="DM you a reminder after a duration (e.g. 10m).")
async def remind_cmd(interaction: discord.Interaction, duration: str, message: str):
    d = _parse_duration(duration)
    if not d:
        await _reply(interaction, _err("Invalid duration."))
        return
    await _reply(interaction, _ok(f"I'll remind you in {_human_delta(d)}."))
    async def _later():
        await asyncio.sleep(d.total_seconds())
        try:
            await interaction.user.send(f"⏰ Reminder: {message}")
        except Exception:
            pass
    asyncio.create_task(_later())


# ============= CONFIG (per-guild) =============
@tree.command(name="setmodlog", description="Set the moderation log channel for this server.")
@guild_only()
@needs_auth()
async def setmodlog_cmd(interaction: discord.Interaction, channel: discord.TextChannel):
    await db.guild_config.update_one(
        {"guild_id": str(interaction.guild.id)},
        {"$set": {"modlog_channel_id": str(channel.id), "guild_id": str(interaction.guild.id)}},
        upsert=True,
    )
    await _reply(interaction, _ok(f"Mod log channel set to {channel.mention}"))


@tree.command(name="modlog", description="Show the current mod log channel.")
@guild_only()
async def modlog_cmd(interaction: discord.Interaction):
    ch = await _get_modlog_channel(interaction.guild)
    await _reply(interaction, f"Mod log channel: {ch.mention if ch else '_not set_'}")


@tree.command(name="autorole", description="Set a role automatically added to new members.")
@guild_only()
@needs_auth()
async def autorole_cmd(interaction: discord.Interaction, role: Optional[discord.Role] = None):
    if role is None:
        await db.guild_config.update_one(
            {"guild_id": str(interaction.guild.id)},
            {"$set": {"autorole_id": None}}, upsert=True,
        )
        await _reply(interaction, _ok("Autorole cleared."))
        return
    await db.guild_config.update_one(
        {"guild_id": str(interaction.guild.id)},
        {"$set": {"autorole_id": str(role.id), "guild_id": str(interaction.guild.id)}},
        upsert=True,
    )
    await _reply(interaction, _ok(f"Autorole set to {role.mention}"))


@tree.command(name="welcome", description="Set welcome channel (posts a message on join).")
@guild_only()
@needs_auth()
async def welcome_cmd(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    if channel is None:
        await db.guild_config.update_one(
            {"guild_id": str(interaction.guild.id)},
            {"$set": {"welcome_channel_id": None}}, upsert=True,
        )
        await _reply(interaction, _ok("Welcome channel cleared."))
        return
    await db.guild_config.update_one(
        {"guild_id": str(interaction.guild.id)},
        {"$set": {"welcome_channel_id": str(channel.id), "guild_id": str(interaction.guild.id)}},
        upsert=True,
    )
    await _reply(interaction, _ok(f"Welcome channel set to {channel.mention}"))


@client.event
async def on_member_join(member: discord.Member):
    doc = await db.guild_config.find_one({"guild_id": str(member.guild.id)}, {"_id": 0})
    if not doc:
        return
    if doc.get("autorole_id"):
        try:
            r = member.guild.get_role(int(doc["autorole_id"]))
            if r: await member.add_roles(r, reason="Autorole")
        except Exception as e:
            _log(f"[autorole] failed: {e}")
    if doc.get("welcome_channel_id"):
        try:
            ch = member.guild.get_channel(int(doc["welcome_channel_id"]))
            if ch:
                await ch.send(f"👋 Welcome {member.mention} to **{member.guild.name}**!")
        except Exception as e:
            _log(f"[welcome] failed: {e}")


# ============= EMOJI =============
@tree.command(name="addemoji", description="Add a new emoji from a URL.")
@guild_only()
@needs_auth()
async def addemoji_cmd(interaction: discord.Interaction, name: str, url: str):
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(url)
            r.raise_for_status()
            emoji = await interaction.guild.create_custom_emoji(name=name, image=r.content)
            await _reply(interaction, _ok(f"Added emoji {emoji}"))
    except Exception as e:
        await _reply(interaction, _err(f"Failed: {e}"))


@tree.command(name="deleteemoji", description="Delete a custom emoji by name.")
@guild_only()
@needs_auth()
async def deleteemoji_cmd(interaction: discord.Interaction, name: str):
    emoji = discord.utils.get(interaction.guild.emojis, name=name)
    if not emoji:
        await _reply(interaction, _err("Emoji not found."))
        return
    await emoji.delete(reason=f"By {interaction.user}")
    await _reply(interaction, _ok(f"Deleted `:{name}:`"))


# ============= HEARTBEAT =============
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
