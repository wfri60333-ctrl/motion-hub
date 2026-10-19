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
intents.members = True
intents.presences = True
intents.voice_states = True

client = discord.Client(intents=intents, application_id=APP_ID)
tree = app_commands.CommandTree(client)
tree.allowed_installs = app_commands.AppInstallationType(guild=True, user=True)
tree.allowed_contexts = app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True)


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


def _is_authorized(member: discord.Member, category: Optional[str] = None) -> bool:
    """Global authorization: Administrator OR member of any ALLOWED_ROLE_IDS.
    If category is provided AND per-category perms are configured, the member
    must ALSO hold one of the roles configured for that category.
    """
    if member.guild_permissions.administrator:
        return True
    role_ids = {r.id for r in getattr(member, "roles", [])}
    # Global allow-list first
    if not any(rid in role_ids for rid in ALLOWED_ROLE_IDS):
        return False
    # Then optional per-category gate
    if category:
        cat_roles = CATEGORY_ROLE_PERMS.get(category) or []
        if cat_roles:  # if configured, member must be in it
            return any(int(r) in role_ids for r in cat_roles if str(r).isdigit())
    return True


async def _refresh_perms_from_backend():
    """Pull latest per-category role gate from the backend/db so dashboard edits take effect."""
    global CATEGORY_ROLE_PERMS
    try:
        doc = await db.bot_config.find_one({}, {"_id": 0, "command_role_perms": 1})
        CATEGORY_ROLE_PERMS = (doc or {}).get("command_role_perms") or {}
    except Exception as e:
        _log(f"[perms] refresh failed: {e}")


# Loaded at startup + refreshed periodically. Shape: {"moderation": ["roleId", ...], ...}
CATEGORY_ROLE_PERMS: Dict[str, list] = {}


# Which slash-command name belongs to which category (mirrors server.py /bot/commands list)
COMMAND_CATEGORY: Dict[str, str] = {
    # moderation
    "wipe": "moderation", "nuke": "moderation", "ban": "moderation", "unban": "moderation",
    "kick": "moderation", "timeout": "moderation", "untimeout": "moderation",
    "warn": "moderation", "warnings": "moderation", "clearwarnings": "moderation",
    "purge": "moderation", "snipe": "moderation", "banlist": "moderation",
    # channel
    "lock": "channel", "unlock": "channel", "hide": "channel", "show": "channel",
    "slowmode": "channel", "rename": "channel", "topic": "channel", "nsfw": "channel",
    "clone": "channel", "createchannel": "channel", "deletechannel": "channel", "channelinfo": "channel",
    # role
    "addrole": "role", "removerole": "role", "createrole": "role", "deleterole": "role",
    "rolecolor": "role", "roleinfo": "role", "rolelist": "role",
    # nickname
    "nick": "nickname", "resetnick": "nickname",
    # voice
    "vmute": "voice", "vunmute": "voice", "deafen": "voice", "undeafen": "voice",
    "disconnect": "voice", "move": "voice",
    # info
    "ping": "info", "uptime": "info", "serverinfo": "info", "userinfo": "info",
    "avatar": "info", "membercount": "info", "invites": "info",
    # utility
    "say": "utility", "embed": "utility", "poll": "utility", "remind": "utility",
    # emoji
    "addemoji": "emoji", "deleteemoji": "emoji",
    # config
    "setmodlog": "config", "modlog": "config", "autorole": "config", "welcome": "config",
    "perms": "config",
    # protection (script/whitelist)
    "panel": "protection", "whitelist": "protection", "revoke": "protection",
    "resethwid": "protection", "forceresethwid": "protection", "keyinfo": "protection",
    "obfuscate": "protection", "unlockkey": "protection",
}


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
    # Load per-category role perms from Mongo
    await _refresh_perms_from_backend()
    _log(f"[perms] loaded per-category role gate: {CATEGORY_ROLE_PERMS}")
    # Register persistent script-panel view (buttons survive restarts)
    try:
        client.add_view(ScriptPanel())
    except Exception as e:
        _log(f"[persistent-view] failed: {e}")
    try:
        client.add_view(FakeIpView())
    except Exception as e:
        _log(f"[fakeip-view] failed: {e}")
    await _push_runtime()
    try:
        await _hub()
    except Exception as exc:
        _log(f"[store] startup failed: {exc}")
    try:
        await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Porn"))
    except Exception as exc:
        _log(f"[presence] {exc}")
    try:
        asyncio.create_task(_sync_commands())
    except Exception as exc:
        _log(f"[sync] {exc}")
    
        


_SYNCED = False


async def _sync_commands():
    global _SYNCED
    if _SYNCED:
        return
    _SYNCED = True
    try:
        keep = {"say", "reply", "fakeip", "dm", "dmreply", "dmlist", "inbox", "chaos", "ping"}
        for cmd in list(tree.get_commands()):
            if cmd.name.lower() not in keep:
                tree.remove_command(cmd.name, type=getattr(cmd, "type", discord.AppCommandType.chat_input))
        synced = await tree.sync()
        _log(f"[sync] {len(synced)} commands")
    except Exception as exc:
        _SYNCED = False
        _log(f"[sync] {exc}")


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
        cmd_name = interaction.command.name if interaction.command else None
        category = COMMAND_CATEGORY.get(cmd_name) if cmd_name else None
        if not m or not _is_authorized(m, category):
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
# say command is defined with the new commands below


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


# ============= AUTOCOMPLETE HELPERS =============
async def target_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for target_id: shows loaders + standalone scripts.
    Discord slash-command dropdown, max 25 items."""
    cur = (current or "").lower()
    choices = []
    try:
        async for l in db.loaders.find({}, {"_id": 0, "id": 1, "name": 1}).sort("created_at", -1).limit(25):
            name = (l.get("name") or "?")
            if not cur or cur in name.lower() or cur in (l.get("id") or ""):
                label = f"📦 {name} — loader"[:100]
                choices.append(app_commands.Choice(name=label, value=l["id"]))
        # Standalone scripts (no loader attached)
        async for s in db.scripts.find(
            {"$or": [{"loader_id": None}, {"loader_id": {"$exists": False}}]},
            {"_id": 0, "id": 1, "name": 1, "level": 1},
        ).sort("created_at", -1).limit(25):
            name = s.get("name") or "?"
            if not cur or cur in name.lower() or cur in (s.get("id") or ""):
                label = f"📄 {name} — script ({s.get('level','?')})"[:100]
                choices.append(app_commands.Choice(name=label, value=s["id"]))
    except Exception as e:
        _log(f"[autocomplete target] {e}")
    return choices[:25]


async def key_autocomplete(interaction: discord.Interaction, current: str):
    """Autocomplete for a whitelist-key string. Shows keys matching input (last-8, discord id, or note)."""
    cur = (current or "").strip().lower()
    choices = []
    try:
        q = {}
        if cur:
            q = {"$or": [
                {"key": {"$regex": cur, "$options": "i"}},
                {"discord_id": cur},
                {"note": {"$regex": cur, "$options": "i"}},
                {"script_name": {"$regex": cur, "$options": "i"}},
                {"loader_name": {"$regex": cur, "$options": "i"}},
            ]}
        async for k in db.wl_keys.find(q, {"_id": 0}).sort("created_at", -1).limit(25):
            scope = k.get("loader_name") or k.get("script_name") or "?"
            key = k.get("key") or ""
            preview = f"{key[:6]}…{key[-4:]}" if len(key) > 12 else key
            note = (k.get("note") or "")[:20]
            label = f"{preview} — {scope}"
            if note: label += f" · {note}"
            if k.get("status") == "locked": label = f"🔒 {label}"
            label = label[:100]
            choices.append(app_commands.Choice(name=label, value=key))
    except Exception as e:
        _log(f"[autocomplete key] {e}")
    return choices[:25]


# ============= SCRIPT PROTECTION (MOD_CTRL native) =============
# These commands use YOUR local database (wl_keys / scripts / mc_panels collections).
# No external service, no affiliation with anyone.
import secrets as _secrets_lib

PUBLIC_API_URL = os.environ.get("PUBLIC_API_URL", "").strip() or BOT_API_URL


async def _find_key(user_key: str) -> Optional[dict]:
    return await db.wl_keys.find_one({"key": user_key}, {"_id": 0})


async def _find_key_by_discord(discord_id: str, script_id: Optional[str] = None,
                               loader_id: Optional[str] = None) -> Optional[dict]:
    """Look up any key linked to a Discord user, optionally scoped to a script OR a loader."""
    q: dict = {"discord_id": discord_id}
    if loader_id:
        q["loader_id"] = loader_id
    elif script_id:
        q["script_id"] = script_id
    return await db.wl_keys.find_one(q, {"_id": 0})


async def _resolve_target(target_id: str) -> tuple[Optional[dict], str]:
    """Given an id, return (doc, kind) where kind is 'script', 'loader', or 'none'."""
    doc = await db.scripts.find_one({"id": target_id}, {"_id": 0, "obfuscated": 0, "source": 0})
    if doc:
        return doc, "script"
    doc = await db.loaders.find_one({"id": target_id}, {"_id": 0})
    if doc:
        return doc, "loader"
    return None, "none"


class RedeemModal(discord.ui.Modal, title="Redeem Your Key"):
    key_input = discord.ui.TextInput(label="Enter your key", min_length=8, max_length=64,
                                     placeholder="paste the key you were given")

    def __init__(self, panel_cfg: dict):
        super().__init__()
        self.panel_cfg = panel_cfg

    async def on_submit(self, interaction: discord.Interaction):
        key_str = str(self.key_input.value).strip()
        row = await _find_key(key_str)
        if not row:
            await interaction.response.send_message(_err("Invalid key."), ephemeral=True)
            return
        # A key must be for either this panel's script or this panel's loader
        panel_script = self.panel_cfg.get("script_id")
        panel_loader = self.panel_cfg.get("loader_id")
        matches = False
        if panel_loader and row.get("loader_id") == panel_loader:
            matches = True
        if panel_script and row.get("script_id") == panel_script:
            matches = True
        if not matches:
            await interaction.response.send_message(
                _err("This key is not for this script/loader."), ephemeral=True)
            return
        # Link discord id
        await db.wl_keys.update_one(
            {"key": key_str},
            {"$set": {"discord_id": str(interaction.user.id)}},
        )
        # Grant role
        role_id = self.panel_cfg.get("customer_role_id")
        if role_id and interaction.guild:
            role = interaction.guild.get_role(int(role_id))
            if role and isinstance(interaction.user, discord.Member):
                try:
                    await interaction.user.add_roles(role, reason="MOD_CTRL: key redeemed")
                except Exception:
                    pass
        await interaction.response.send_message(
            _ok("Key linked to your Discord account. You can now click **Get Script**."),
            ephemeral=True,
        )


class ResetHwidModal(discord.ui.Modal, title="Reset HWID"):
    key_input = discord.ui.TextInput(label="Your key", min_length=8, max_length=64)

    async def on_submit(self, interaction: discord.Interaction):
        key_str = str(self.key_input.value).strip()
        # Hit the backend which enforces the configured cooldown + logs the event
        try:
            async with httpx.AsyncClient(timeout=6) as http:
                r = await http.post(f"{BOT_API_URL}/api/keys/user/resethwid",
                                    json={"key": key_str})
        except Exception as e:
            # Backend unreachable → fall back to direct Mongo write WITH cooldown check
            row = await _find_key(key_str)
            if not row:
                await interaction.response.send_message(_err("Invalid key."), ephemeral=True); return
            if row.get("status") == "locked":
                await interaction.response.send_message(
                    _err("Key is locked. Ask an admin to reset it."), ephemeral=True); return
            cfg = await db.bot_config.find_one({}, {"_id": 0}) or {}
            cooldown_h = int(cfg.get("hwid_reset_cooldown_hours") or 24)
            last_reset = row.get("hwid_reset_at")
            if last_reset and cooldown_h > 0:
                try:
                    elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last_reset)
                    remaining = timedelta(hours=cooldown_h) - elapsed
                    if remaining.total_seconds() > 0:
                        total = int(remaining.total_seconds())
                        h, rem = divmod(total, 3600); m, _ = divmod(rem, 60)
                        await interaction.response.send_message(
                            _err(f"Cooldown active. Try again in {h}h {m}m."), ephemeral=True); return
                except Exception:
                    pass
            now = datetime.now(timezone.utc).isoformat()
            await db.wl_keys.update_one(
                {"key": key_str},
                {"$set": {"hwid": None, "hwid_reset_at": now, "hwid_mismatch_count": 0}},
            )
            await interaction.response.send_message(
                _ok("HWID reset. Re-run the script to bind fresh."), ephemeral=True)
            return
        # Success/failure path when backend was reached
        if r.status_code == 200:
            await interaction.response.send_message(
                _ok("HWID reset. Re-run the script to bind fresh."), ephemeral=True)
        elif r.status_code == 404:
            await interaction.response.send_message(_err("Invalid key."), ephemeral=True)
        elif r.status_code == 429:
            try:
                detail = r.json().get("detail", "Cooldown active. Try again later.")
            except Exception:
                detail = "Cooldown active. Try again later."
            await interaction.response.send_message(_err(detail), ephemeral=True)
        elif r.status_code == 403:
            try:
                detail = r.json().get("detail", "Key is locked.")
            except Exception:
                detail = "Key is locked."
            await interaction.response.send_message(_err(detail), ephemeral=True)
        else:
            await interaction.response.send_message(
                _err(f"Reset failed ({r.status_code})."), ephemeral=True)


class ScriptPanel(discord.ui.View):
    """Persistent panel view. Config lookup by message_id from mc_panels collection."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _cfg(self, interaction: discord.Interaction) -> Optional[dict]:
        msg = interaction.message
        if not msg:
            return None
        cfg = await db.mc_panels.find_one({"message_id": str(msg.id)}, {"_id": 0})
        if not cfg:
            await interaction.response.send_message(
                _err("Panel config missing. Ask an admin to re-run /panel."),
                ephemeral=True)
        return cfg

    @discord.ui.button(label="Redeem Key", style=discord.ButtonStyle.primary,
                       emoji="🔑", custom_id="mc_redeem")
    async def redeem(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await self._cfg(interaction)
        if not cfg: return
        await interaction.response.send_modal(RedeemModal(cfg))

    @discord.ui.button(label="Get Script", style=discord.ButtonStyle.primary,
                       emoji="📥", custom_id="mc_getscript")
    async def getscript(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await self._cfg(interaction)
        if not cfg: return
        row = await _find_key_by_discord(
            str(interaction.user.id),
            script_id=cfg.get("script_id"),
            loader_id=cfg.get("loader_id"),
        )
        if not row:
            await interaction.response.send_message(
                _err("No key linked to your Discord. Click **Redeem Key** first."),
                ephemeral=True)
            return
        if cfg.get("loader_id"):
            # Loader panel → give the all-in-one bundle URL (runs every script in the loader)
            loader_url = f"{PUBLIC_API_URL}/api/loader/{cfg['loader_id']}/bundle.lua"
            footer = "Bundle loader — runs every script in this loader. Key is bound to your account & HWID."
        else:
            loader_url = f"{PUBLIC_API_URL}/api/loader/{cfg['script_id']}.lua"
            footer = "Paste into your executor. Key is bound to your account & HWID."
        snippet = f'script_key = "{row["key"]}"\nloadstring(game:HttpGet("{loader_url}"))()'
        e = discord.Embed(
            title="📥 Your Script",
            description=f"```lua\n{snippet}\n```",
            color=0x007AFF,
        )
        e.set_footer(text=footer)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @discord.ui.button(label="Get Role", style=discord.ButtonStyle.success,
                       emoji="👤", custom_id="mc_getrole")
    async def getrole(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await self._cfg(interaction)
        if not cfg: return
        row = await _find_key_by_discord(
            str(interaction.user.id),
            script_id=cfg.get("script_id"),
            loader_id=cfg.get("loader_id"),
        )
        if not row:
            await interaction.response.send_message(
                _err("No key linked. Redeem a key first."), ephemeral=True)
            return
        role_id = cfg.get("customer_role_id")
        if not role_id or not interaction.guild:
            await interaction.response.send_message(_err("Customer role not configured."),
                                                    ephemeral=True)
            return
        role = interaction.guild.get_role(int(role_id))
        if not role:
            await interaction.response.send_message(_err("Customer role missing."),
                                                    ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="MOD_CTRL: role claim")
            await interaction.response.send_message(_ok(f"Granted {role.mention}"),
                                                    ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(_err(f"Failed: {e}"), ephemeral=True)

    @discord.ui.button(label="Reset HWID", style=discord.ButtonStyle.danger,
                       emoji="🔄", custom_id="mc_resethwid")
    async def resethwid(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ResetHwidModal())

    @discord.ui.button(label="Get Stats", style=discord.ButtonStyle.secondary,
                       emoji="📊", custom_id="mc_getstats")
    async def getstats(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await self._cfg(interaction)
        if not cfg: return
        row = await _find_key_by_discord(
            str(interaction.user.id),
            script_id=cfg.get("script_id"),
            loader_id=cfg.get("loader_id"),
        )
        if not row:
            await interaction.response.send_message(
                _err("No key linked to your Discord."), ephemeral=True)
            return
        # Cooldown calc
        bot_cfg = await db.bot_config.find_one({}, {"_id": 0}) or {}
        cooldown_h = int(bot_cfg.get("hwid_reset_cooldown_hours") or 24)
        cd_line = "ready"
        last_reset = row.get("hwid_reset_at")
        if last_reset and cooldown_h > 0:
            try:
                elapsed = datetime.now(timezone.utc) - datetime.fromisoformat(last_reset)
                remaining = timedelta(hours=cooldown_h) - elapsed
                if remaining.total_seconds() > 0:
                    total = int(remaining.total_seconds())
                    h, rem = divmod(total, 3600); m, _ = divmod(rem, 60)
                    cd_line = f"{h}h {m}m left"
            except Exception:
                pass
        e = discord.Embed(title="📊 Your Stats", color=0x007AFF)
        e.add_field(name="Key", value=f"||`{row.get('key', '?')}`||", inline=False)
        e.add_field(name="Status", value=str(row.get("status", "active")))
        e.add_field(name="Executions", value=str(row.get("executions", 0)))
        e.add_field(name="HWID", value="🔒 locked" if row.get("hwid") else "🔓 unbound")
        e.add_field(name="Reset cooldown", value=cd_line)
        e.add_field(name="Mismatches", value=str(row.get("hwid_mismatch_count", 0)))
        e.add_field(name="Expires", value=str(row.get("expires_at") or "never"))
        e.add_field(name="Last used", value=str(row.get("last_used") or "never"))
        e.add_field(name="Note", value=str(row.get("note") or "—"), inline=False)
        await interaction.response.send_message(embed=e, ephemeral=True)


@tree.command(name="panel", description="Create your MOD_CTRL script panel with 5 buttons.")
@app_commands.describe(
    display_name="Display name shown on the panel (e.g. 'Yuna - Custom Loader')",
    target_id="Your MOD_CTRL script ID OR loader ID (from the dashboard)",
    customer_role="Role granted to users after redeeming a key",
)
@guild_only()
@needs_auth()
async def panel_cmd(interaction: discord.Interaction, display_name: str,
                    target_id: str, customer_role: discord.Role):
    target_id = target_id.strip()
    target, kind = await _resolve_target(target_id)
    if not target:
        await _reply(interaction, _err(
            "ID not found. Paste a Script ID from the Scripts page OR a Loader ID from the Loaders page."))
        return

    if kind == "loader":
        scripts_in_loader = await db.scripts.count_documents({"loader_id": target_id})
        subtitle = f"Loader • {scripts_in_loader} script(s) bundled"
    else:
        subtitle = f"Script • {target.get('level', '?').upper()}"

    description = (
        f"**{display_name}**\n_{subtitle}_\n\n"
        "Use the buttons below to manage your account:\n"
        "• **Redeem Key** — link your key to your Discord\n"
        "• **Get Script** — copy the loader snippet for your executor\n"
        "• **Get Role** — receive your customer role\n"
        "• **Reset HWID** — bind a new device (cooldown enforced)\n"
        "• **Get Stats** — view your account info"
    )
    embed = discord.Embed(
        title=f"{display_name} — Panel",
        description=description,
        color=0x007AFF,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=f"MOD_CTRL • {kind}")

    await interaction.response.send_message(embed=embed, view=ScriptPanel())
    msg = await interaction.original_response()

    panel_doc = {
        "message_id": str(msg.id),
        "channel_id": str(interaction.channel.id),
        "guild_id": str(interaction.guild.id),
        "script_name": display_name,
        "customer_role_id": str(customer_role.id),
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if kind == "loader":
        panel_doc["loader_id"] = target_id
        panel_doc["script_id"] = None
    else:
        panel_doc["script_id"] = target_id
        panel_doc["loader_id"] = None
    await db.mc_panels.update_one(
        {"message_id": str(msg.id)},
        {"$set": panel_doc},
        upsert=True,
    )
    _log(f"[panel] created: guild={interaction.guild.id} kind={kind} target={target_id}")


@panel_cmd.autocomplete("target_id")
async def _ac_panel_target(interaction, current):
    return await target_autocomplete(interaction, current)


@tree.command(name="whitelist", description="Whitelist a user for a script/loader and grant them a role. No key is DM'd.")
@app_commands.describe(
    user="Discord user to whitelist",
    target_id="Script ID OR Loader ID (from the dashboard)",
    role="Role to grant the user (this is the role that unlocks the panel for them)",
    days="Days until access expires (0 = never)",
    note="Optional note",
)
@guild_only()
@needs_auth()
async def whitelist_cmd(interaction: discord.Interaction, user: discord.Member,
                        target_id: str, role: discord.Role,
                        days: Optional[int] = 0, note: Optional[str] = None):
    target_id = target_id.strip()
    target, kind = await _resolve_target(target_id)
    if not target:
        await _reply(interaction, _err(
            "ID not found. Paste a Script ID or a Loader ID from the dashboard."))
        return

    now = datetime.now(timezone.utc)
    expires_at = None
    if days and days > 0:
        expires_at = (now + timedelta(days=int(days))).isoformat()

    # Grant the role first
    role_ok = True
    role_err = ""
    try:
        await user.add_roles(role, reason=f"MOD_CTRL: whitelisted by {interaction.user}")
    except discord.Forbidden:
        role_ok = False
        role_err = "role hierarchy — the bot's top role must be above the target role"
    except Exception as e:
        role_ok = False
        role_err = str(e)

    # Check for existing whitelist to prevent duplicates
    scope_filter = ({"loader_id": target_id} if kind == "loader"
                    else {"script_id": target_id})
    existing = await db.wl_keys.find_one(
        {"discord_id": str(user.id), **scope_filter, "status": "active"},
        {"_id": 0},
    )
    if existing:
        # Refresh expiry and note, but keep the same silent key
        upd = {"note": note, "granted_role_id": str(role.id)}
        if expires_at:
            upd["expires_at"] = expires_at
        await db.wl_keys.update_one({"id": existing["id"]}, {"$set": upd})
        msg = f"Already whitelisted for **{target.get('name') or target_id}** ({kind}); refreshed expiry."
    else:
        key_str = _secrets_lib.token_urlsafe(24)
        doc = {
            "id": str(_secrets_lib.token_hex(16)),
            "key": key_str,
            "script_id": target_id if kind == "script" else None,
            "script_name": target.get("name") if kind == "script" else None,
            "loader_id": target_id if kind == "loader" else None,
            "loader_name": target.get("name") if kind == "loader" else None,
            "discord_id": str(user.id),
            "granted_role_id": str(role.id),
            "note": note,
            "hwid": None,
            "status": "active",
            "executions": 0,
            "created_at": now.isoformat(),
            "expires_at": expires_at,
            "last_used": None,
            "silent": True,  # Marker: key was never shown to the user
        }
        await db.wl_keys.insert_one(doc)
        msg = f"Whitelisted for **{target.get('name') or target_id}** ({kind})."

    if role_ok:
        role_line = f"Role granted: {role.mention}"
    else:
        role_line = f"⚠️  Could not grant {role.mention}: {role_err}"

    await _reply(
        interaction,
        _ok(f"{user.mention}: {msg}\n{role_line}\n"
            f"They can now click **Get Script** on the panel to receive their loader."),
        ephemeral=False,
    )
    await _post_audit({
        "guild_id": str(interaction.guild.id), "guild_name": interaction.guild.name,
        "actor_id": str(interaction.user.id), "actor_name": str(interaction.user),
        "action": "whitelist",
        "details": {"target_id": target_id, "kind": kind, "user": str(user),
                    "role": str(role), "expires_at": expires_at},
    })


@whitelist_cmd.autocomplete("target_id")
async def _ac_whitelist_target(interaction, current):
    return await target_autocomplete(interaction, current)


@tree.command(name="revoke", description="Revoke a key (immediate).")
@app_commands.describe(user_key="The whitelist key to revoke")
@guild_only()
@needs_auth()
async def revoke_cmd(interaction: discord.Interaction, user_key: str):
    r = await db.wl_keys.delete_one({"key": user_key})
    if r.deleted_count:
        await _reply(interaction, _ok("Key revoked."))
    else:
        await _reply(interaction, _err("Key not found."))


@revoke_cmd.autocomplete("user_key")
async def _ac_revoke_key(interaction, current):
    return await key_autocomplete(interaction, current)


@tree.command(name="resethwid", description="Force-reset HWID for a key (admin — bypasses cooldown & unlocks).")
@app_commands.describe(user_key="The whitelist key to reset")
@guild_only()
@needs_auth()
async def resethwid_cmd(interaction: discord.Interaction, user_key: str):
    row = await db.wl_keys.find_one({"key": user_key}, {"_id": 0})
    if not row:
        await _reply(interaction, _err("Key not found."))
        return
    now = datetime.now(timezone.utc).isoformat()
    await db.wl_keys.update_one(
        {"key": user_key},
        {"$set": {"hwid": None, "hwid_reset_at": now,
                  "hwid_mismatch_count": 0, "status": "active"}},
    )
    try:
        await db.hwid_events.insert_one({
            "id": _secrets_lib.token_hex(16),
            "key_id": row.get("id"), "key": user_key,
            "event": "admin_force_reset",
            "actor": str(interaction.user.id),
            "actor_name": str(interaction.user),
            "ts": now,
        })
    except Exception:
        pass
    await _reply(interaction, _ok(f"Force-reset HWID for key. Cooldown cleared, mismatch counter zeroed, key unlocked."))


@resethwid_cmd.autocomplete("user_key")
async def _ac_reset_key(interaction, current):
    return await key_autocomplete(interaction, current)


@tree.command(name="forceresethwid", description="Alias of /resethwid — force-reset a user's HWID and unlock.")
@app_commands.describe(user_key="The whitelist key to reset")
@guild_only()
@needs_auth()
async def forceresethwid_cmd(interaction: discord.Interaction, user_key: str):
    await resethwid_cmd.callback(interaction, user_key)


@forceresethwid_cmd.autocomplete("user_key")
async def _ac_force_reset_key(interaction, current):
    return await key_autocomplete(interaction, current)


@tree.command(name="unlockkey", description="Unlock a key that got auto-locked from HWID mismatches.")
@app_commands.describe(user_key="The whitelist key to unlock")
@guild_only()
@needs_auth()
async def unlockkey_cmd(interaction: discord.Interaction, user_key: str):
    r = await db.wl_keys.update_one(
        {"key": user_key},
        {"$set": {"status": "active", "hwid_mismatch_count": 0}},
    )
    if r.matched_count:
        try:
            await db.hwid_events.insert_one({
                "id": _secrets_lib.token_hex(16),
                "key": user_key, "event": "admin_unlock",
                "actor": str(interaction.user.id),
                "actor_name": str(interaction.user),
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
        await _reply(interaction, _ok("Key unlocked."))
    else:
        await _reply(interaction, _err("Key not found."))


@unlockkey_cmd.autocomplete("user_key")
async def _ac_unlock_key(interaction, current):
    return await key_autocomplete(interaction, current)


@tree.command(name="perms", description="View or set per-category role permissions for this bot.")
@app_commands.describe(category="e.g. moderation, protection, channel, role, voice, config",
                       role="Role required to use commands in this category (omit to clear)")
@guild_only()
@needs_auth()
async def perms_cmd(interaction: discord.Interaction, category: Optional[str] = None,
                    role: Optional[discord.Role] = None):
    doc = await db.bot_config.find_one({}, {"_id": 0}) or {}
    perms = doc.get("command_role_perms") or {}
    if not category:
        if not perms:
            await _reply(interaction, "_No per-category role gate configured (using global allow-list only)._")
            return
        lines = ["**Per-category role gate:**"]
        for cat, ids in perms.items():
            mentions = ", ".join(f"<@&{rid}>" for rid in ids) or "_none_"
            lines.append(f"• `{cat}` → {mentions}")
        await _reply(interaction, "\n".join(lines))
        return
    category = category.strip().lower()
    cur = list(perms.get(category, []))
    if role is None:
        # Clear the category
        perms.pop(category, None)
        await db.bot_config.update_one({}, {"$set": {"command_role_perms": perms}})
        await _refresh_perms_from_backend()
        await _reply(interaction, _ok(f"Cleared role gate for `{category}` (falls back to global)."))
        return
    rid = str(role.id)
    if rid in cur:
        cur.remove(rid)
        msg = f"Removed {role.mention} from `{category}` gate."
    else:
        cur.append(rid)
        msg = f"Added {role.mention} to `{category}` gate."
    perms[category] = cur
    await db.bot_config.update_one({}, {"$set": {"command_role_perms": perms}})
    await _refresh_perms_from_backend()
    await _reply(interaction, _ok(msg))


@tree.command(name="keyinfo", description="Look up details of a key.")
@guild_only()
@needs_auth()
async def keyinfo_cmd(interaction: discord.Interaction, user_key: str):
    row = await _find_key(user_key)
    if not row:
        await _reply(interaction, _err("Key not found."))
        return
    scope = (
        f"Loader: {row.get('loader_name') or row.get('loader_id')}"
        if row.get("loader_id")
        else f"Script: {row.get('script_name') or row.get('script_id')}"
    )
    e = discord.Embed(title="🔑 Key Details", color=0x007AFF)
    e.add_field(name="Scope", value=scope, inline=False)
    e.add_field(name="Discord", value=str(row.get("discord_id") or "—"))
    e.add_field(name="Status", value=str(row.get("status", "active")))
    e.add_field(name="Executions", value=str(row.get("executions", 0)))
    e.add_field(name="HWID", value="🔒 locked" if row.get("hwid") else "🔓 unbound")
    e.add_field(name="Mismatches", value=str(row.get("hwid_mismatch_count", 0)))
    e.add_field(name="Expires", value=str(row.get("expires_at") or "never"))
    e.add_field(name="Last used", value=str(row.get("last_used") or "never"))
    await _reply(interaction, "", embed=e, ephemeral=False)


@keyinfo_cmd.autocomplete("user_key")
async def _ac_keyinfo_key(interaction, current):
    return await key_autocomplete(interaction, current)


@tree.command(name="obfuscate", description="Obfuscate an attached .lua file.")
@app_commands.describe(file="Your .lua file (max 500 KB)", level="Protection intensity")
@app_commands.choices(level=[
    app_commands.Choice(name="Light — strings only", value="light"),
    app_commands.Choice(name="Medium — strings + numbers", value="medium"),
    app_commands.Choice(name="Heavy — 3 layers + anti-hook", value="heavy"),
])
@guild_only()
@needs_auth()
async def obfuscate_cmd(interaction: discord.Interaction, file: discord.Attachment,
                        level: Optional[app_commands.Choice[str]] = None):
    lvl = level.value if level else "medium"
    if file.size > 500_000:
        await _reply(interaction, _err("File too large (max 500 KB)."))
        return
    if not (file.filename.endswith(".lua") or file.filename.endswith(".txt")):
        await _reply(interaction, _err("Attach a `.lua` or `.txt` file."))
        return
    await interaction.response.defer(ephemeral=True)
    try:
        raw = await file.read()
        code = raw.decode("utf-8", errors="replace")
    except Exception as e:
        await interaction.followup.send(_err(f"Failed to read file: {e}"), ephemeral=True)
        return
    try:
        async with httpx.AsyncClient(timeout=45) as http:
            r = await http.post(f"{BOT_API_URL}/api/obfuscate",
                                json={"code": code, "level": lvl})
            if r.status_code >= 400:
                await interaction.followup.send(
                    _err(f"Obfuscator API returned {r.status_code}: {r.text[:300]}"),
                    ephemeral=True)
                return
            data = r.json()
            output = data.get("output", "")
            engine = data.get("engine", "?")
    except Exception as e:
        await interaction.followup.send(_err(f"Failed to reach obfuscator: {e}"), ephemeral=True)
        return

    import io as _io
    out_name = file.filename.rsplit(".", 1)[0] + f"_obf_{lvl}.lua"
    buf = _io.BytesIO(output.encode("utf-8"))
    discord_file = discord.File(buf, filename=out_name)
    embed = discord.Embed(title="✨ Obfuscation Complete", color=0x34C759)
    embed.add_field(name="Level", value=lvl.upper(), inline=True)
    embed.add_field(name="Engine", value=engine, inline=True)
    embed.add_field(name="Input", value=f"{len(code)} bytes", inline=True)
    embed.add_field(name="Output", value=f"{len(output)} bytes", inline=True)
    embed.add_field(name="Inflation", value=f"×{len(output)/max(1,len(code)):.1f}", inline=True)
    await interaction.followup.send(embed=embed, file=discord_file, ephemeral=True)


# ============= NEW COMMANDS =============
import io as _io
import json as _json
import random as _random
import re as _re
import time as _time

_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hub_store.json")
_HUB = None


def _blank_store():
    return {"inbox": None, "convos": {}, "contacted": {}}


def _norm_ts(value):
    try:
        n = int(value)
    except Exception:
        return int(_time.time())
    if n > 10_000_000_000:
        n //= 1000
    return n


def _seed_store():
    log = [
        {"dir": "out", "text": "yo", "at": _norm_ts(1792379892482)},
        {"dir": "in", "text": "Yoo", "at": _norm_ts(1792379903767)},
        {"dir": "out", "text": "wsp", "at": _norm_ts(1792379910734)},
        {"dir": "in", "text": "Who the tf is this 🤣🤣🤣?", "at": _norm_ts(1792379928068)},
        {"dir": "out", "text": "lmao i’m just a bot made by nxtro", "at": _norm_ts(1792379944954)},
        {"dir": "in", "text": "Ohh bet", "at": _norm_ts(1792379962558)},
        {"dir": "out", "text": "i’m just gathering your information while he does stuff", "at": _norm_ts(1792379988585)},
        {"dir": "in", "text": "Wym", "at": _norm_ts(1792380158322)},
        {"dir": "out", "text": "hey", "at": _norm_ts(1792413443241)},
    ]
    uid = "1261164075979898970"
    outs = sum(1 for entry in log if entry["dir"] == "out")
    ins = sum(1 for entry in log if entry["dir"] == "in")
    store = _blank_store()
    store["inbox"] = "1387643893641777244"
    store["convos"][uid] = {"owner": "1387643893641777244", "log": log}
    store["contacted"][uid] = {
        "name": "thugginjeff",
        "username": ".d.b.j",
        "count": outs + ins,
        "out": outs,
        "in": ins,
        "last": log[-1]["at"],
    }
    return store


async def _hub():
    global _HUB
    if _HUB is not None:
        return _HUB
    try:
        doc = await db.dm_hub.find_one({"_id": "store"})
        data = (doc or {}).get("data")
        if isinstance(data, dict) and (data.get("contacted") or data.get("convos")):
            _HUB = data
            return _HUB
    except Exception as exc:
        _log(f"[store] load failed: {exc}")
    _HUB = _seed_store()
    await _save_store()
    return _HUB


async def _save_store():
    if _HUB is None:
        return
    try:
        await db.dm_hub.update_one({"_id": "store"}, {"$set": {"data": _HUB}}, upsert=True)
    except Exception as exc:
        _log(f"[store] mongo save failed: {exc}")
    try:
        with open(_STORE_PATH, "w", encoding="utf-8") as fh:
            _json.dump(_HUB, fh)
    except Exception as exc:
        _log(f"[store] file save failed: {exc}")


def _opt(interaction: discord.Interaction, name: str):
    for opt in (interaction.data or {}).get("options") or []:
        if opt.get("name") == name:
            return opt.get("value")
    return None


def _parse_ref(text: str, fallback_channel):
    match = _re.search(r"channels/\d+/(\d+)/(\d+)", text or "")
    if match:
        return int(match.group(1)), int(match.group(2))
    digits = _re.sub(r"\D", "", text or "")
    if digits and fallback_channel:
        return int(fallback_channel), int(digits)
    return None


async def _person(interaction: discord.Interaction, user: Optional[discord.User], raw_id: Optional[str]):
    if user is not None:
        return user
    digits = _re.sub(r"\D", "", raw_id or "")
    if not digits:
        return None
    try:
        return await interaction.client.fetch_user(int(digits))
    except Exception:
        return None


async def _file_from(attachment: Optional[discord.Attachment]):
    if attachment is None:
        return None
    raw = await attachment.read()
    return discord.File(_io.BytesIO(raw), filename=attachment.filename)


async def _post_quiet(interaction: discord.Interaction, content: Optional[str], channel_id, attachment=None, reference_id=None):
    channel_id = int(channel_id)
    kwargs = {"allowed_mentions": discord.AllowedMentions.none()}
    if content:
        kwargs["content"] = content[:2000]
    if reference_id:
        kwargs["reference"] = discord.MessageReference(
            message_id=int(reference_id), channel_id=channel_id, fail_if_not_exists=False
        )
    channel = interaction.client.get_channel(channel_id)
    if channel is not None:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        try:
            discord_file = await _file_from(attachment)
            if discord_file:
                await channel.send(file=discord_file, **kwargs)
            else:
                await channel.send(**kwargs)
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
            return
        except Exception as exc:
            _log(f"[post] {exc}")
            await interaction.followup.send("Couldn't send that.", ephemeral=True)
            return
    discord_file = await _file_from(attachment)
    if interaction.response.is_done():
        return
    payload = {"allowed_mentions": discord.AllowedMentions.none()}
    if content:
        payload["content"] = content[:2000]
    if discord_file is not None and reference_id is None:
        payload["file"] = discord_file
        await interaction.response.send_message(**payload)
        return
    data = {"allowed_mentions": {"parse": [], "replied_user": bool(reference_id)}}
    if content:
        data["content"] = content[:2000]
    if reference_id:
        data["message_reference"] = {
            "message_id": str(reference_id),
            "channel_id": str(channel_id),
            "fail_if_not_exists": False,
        }
    route = discord.http.Route(
        "POST",
        "/interactions/{interaction_id}/{interaction_token}/callback",
        interaction_id=interaction.id,
        interaction_token=interaction.token,
    )
    await interaction.client.http.request(route, json={"type": 4, "data": data})


_BASES = [
    (1, 1, 13335, "Cloudflare", "Sydney", "New South Wales", "AU", "Australia/Sydney", -33.8688, 151.2093, "CDN"),
    (8, 8, 15169, "Google", "Mountain View", "California", "US", "America/Los_Angeles", 37.386, -122.0838, "Corporate"),
    (9, 9, 19281, "Quad9", "Berkeley", "California", "US", "America/Los_Angeles", 37.8715, -122.273, "Corporate"),
    (4, 2, 3356, "Level 3", "Broomfield", "Colorado", "US", "America/Denver", 39.9205, -105.0867, "Hosting"),
    (23, 21, 7922, "Comcast", "Philadelphia", "Pennsylvania", "US", "America/New_York", 39.9526, -75.1652, "Residential"),
    (24, 15, 7922, "Comcast", "Chicago", "Illinois", "US", "America/Chicago", 41.8781, -87.6298, "Residential"),
    (50, 16, 7922, "Comcast", "Houston", "Texas", "US", "America/Chicago", 29.7604, -95.3698, "Residential"),
    (68, 40, 7018, "AT&T", "Dallas", "Texas", "US", "America/Chicago", 32.7767, -96.797, "Residential"),
    (69, 15, 701, "Verizon", "Ashburn", "Virginia", "US", "America/New_York", 39.0438, -77.4874, "Residential"),
    (71, 16, 21928, "T-Mobile", "Bellevue", "Washington", "US", "America/Los_Angeles", 47.6101, -122.2015, "Mobile"),
    (72, 80, 6167, "Verizon", "New York", "New York", "US", "America/New_York", 40.7128, -74.006, "Residential"),
    (73, 50, 7922, "Comcast", "Denver", "Colorado", "US", "America/Denver", 39.7392, -104.9903, "Residential"),
    (74, 90, 20115, "Charter", "Stamford", "Connecticut", "US", "America/New_York", 41.0534, -73.5387, "Residential"),
    (75, 80, 22773, "Cox", "Atlanta", "Georgia", "US", "America/New_York", 33.749, -84.388, "Residential"),
    (76, 20, 20001, "Charter", "Los Angeles", "California", "US", "America/Los_Angeles", 34.0522, -118.2437, "Residential"),
    (96, 40, 6167, "Verizon", "Boston", "Massachusetts", "US", "America/New_York", 42.3601, -71.0589, "Residential"),
    (98, 20, 7018, "AT&T", "Miami", "Florida", "US", "America/New_York", 25.7617, -80.1918, "Residential"),
    (99, 10, 11427, "Charter", "Seattle", "Washington", "US", "America/Los_Angeles", 47.6062, -122.3321, "Residential"),
    (104, 16, 13335, "Cloudflare", "San Francisco", "California", "US", "America/Los_Angeles", 37.7749, -122.4194, "CDN"),
    (108, 20, 16509, "Amazon", "Ashburn", "Virginia", "US", "America/New_York", 39.0438, -77.4874, "Hosting"),
    (136, 20, 8075, "Microsoft", "Des Moines", "Iowa", "US", "America/Chicago", 41.5868, -93.625, "Hosting"),
    (142, 250, 209, "CenturyLink", "Monroe", "Louisiana", "US", "America/Chicago", 32.5093, -92.1193, "Residential"),
    (151, 101, 20940, "Akamai", "Cambridge", "Massachusetts", "US", "America/New_York", 42.3736, -71.1097, "CDN"),
    (157, 240, 16509, "Amazon", "Boardman", "Oregon", "US", "America/Los_Angeles", 45.8399, -119.7006, "Hosting"),
    (162, 158, 14618, "Amazon", "Dublin", "Leinster", "IE", "Europe/Dublin", 53.3498, -6.2603, "Hosting"),
    (172, 64, 36351, "SoftLayer", "Dallas", "Texas", "US", "America/Chicago", 32.7767, -96.797, "Hosting"),
    (173, 245, 15169, "Google", "Council Bluffs", "Iowa", "US", "America/Chicago", 41.2619, -95.8608, "Corporate"),
    (174, 16, 7018, "AT&T", "Atlanta", "Georgia", "US", "America/New_York", 33.749, -84.388, "Residential"),
    (184, 80, 209, "Lumen", "Monroe", "Louisiana", "US", "America/Chicago", 32.5093, -92.1193, "Residential"),
    (185, 20, 2856, "BT", "London", "England", "GB", "Europe/London", 51.5074, -0.1278, "Residential"),
    (188, 114, 3320, "Deutsche Telekom", "Frankfurt", "Hesse", "DE", "Europe/Berlin", 50.1109, 8.6821, "Residential"),
    (191, 96, 28573, "Claro", "Sao Paulo", "Sao Paulo", "BR", "America/Sao_Paulo", -23.5558, -46.6396, "Residential"),
    (193, 70, 16276, "OVH", "Gravelines", "Hauts-de-France", "FR", "Europe/Paris", 50.987, 2.125, "Hosting"),
    (194, 60, 24940, "Hetzner", "Falkenstein", "Saxony", "DE", "Europe/Berlin", 50.4779, 12.3713, "Hosting"),
    (195, 20, 5089, "Virgin Media", "London", "England", "GB", "Europe/London", 51.5074, -0.1278, "Residential"),
    (202, 10, 4766, "Korea Telecom", "Seoul", "Seoul", "KR", "Asia/Seoul", 37.5665, 126.978, "Residential"),
    (203, 10, 4134, "China Telecom", "Shanghai", "Shanghai", "CN", "Asia/Shanghai", 31.2304, 121.4737, "Residential"),
    (210, 50, 2516, "KDDI", "Tokyo", "Tokyo", "JP", "Asia/Tokyo", 35.6762, 139.6503, "Residential"),
    (212, 58, 1273, "Vodafone", "Dusseldorf", "North Rhine-Westphalia", "DE", "Europe/Berlin", 51.2277, 6.7735, "Mobile"),
    (213, 10, 3215, "Orange", "Paris", "Ile-de-France", "FR", "Europe/Paris", 48.8566, 2.3522, "Residential"),
]
_FAKE_NETS = []
for _a, _b, _asn, _org, _city, _region, _cc, _tz, _lat, _lon, _kind in _BASES:
    for _third in (4, 18, 37):
        _FAKE_NETS.append((_a, _b, _third, _asn, _org, _city, _region, _cc, _tz, _lat, _lon, _kind))


def _fake_report(user: discord.abc.User) -> str:
    net = _random.choice(_FAKE_NETS)
    ip = f"{net[0]}.{net[1]}.{net[2]}.{_random.randint(1, 254)}"
    if ip.startswith(("10.", "127.", "192.168.", "172.16.", "172.17.", "172.18.", "172.19.", "172.2", "172.30.", "172.31.", "0.")):
        ip = f"{net[0]}.{net[1]}.{net[2]}.{_random.randint(20, 240)}"
    asn, org, city, region, cc, zone, lat, lon, kind = net[3:]
    slug = _re.sub(r"[^a-z]", "", org.lower())[:12] or "net"
    host = f"pool-{ip.replace('.', '-')}.{slug}.net"
    lines = [
        "NETWORK TRACE  ·  RESOLVED",
        f"target        {user.name}",
        f"user id       {user.id}",
        f"ipv4          {ip}",
        f"prefix        {net[0]}.{net[1]}.{net[2]}.0/24",
        f"gateway       {net[0]}.{net[1]}.{net[2]}.1",
        f"hostname      {host}",
        f"ptr           {host}",
        f"isp           {org}",
        f"asn           AS{asn} {org.upper()}",
        f"type          {kind}",
        f"location      {city}, {region}, {cc}",
        f"timezone      {zone}",
        f"coordinates   {lat + _random.uniform(-0.08, 0.08):.4f}, {lon + _random.uniform(-0.08, 0.08):.4f}",
        f"vpn           {'yes' if _random.random() < 0.22 else 'no'}",
        f"proxy         {'yes' if _random.random() < 0.16 else 'no'}",
        f"hosting       {'yes' if kind in ('Hosting', 'CDN') else 'no'}",
        f"mobile        {'yes' if kind == 'Mobile' else 'no'}",
        f"rtt           {_random.randint(8, 180)} ms",
        f"loss          {_random.random() * 2:.1f}%",
        f"threat        {_random.randint(0, 40)}/100",
        f"seen          {datetime.now(timezone.utc).isoformat()}",
    ]
    return "\n".join(lines)


class FakeIpSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="Make a selection", min_values=1, max_values=1, custom_id="fakeip:pick")

    async def callback(self, interaction: discord.Interaction):
        user = self.values[0]
        report = _fake_report(user)
        embed = discord.Embed(title="NETWORK TRACE  ·  RESOLVED", description=f"```\n{report}\n```", color=0x34C759)
        embed.set_footer(text="Generated lookup")
        await interaction.response.send_message(content=user.mention, embed=embed, allowed_mentions=discord.AllowedMentions(users=[user]))


class FakeIpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(FakeIpSelect())


async def _remember(user: discord.abc.User, text: str, direction: str):
    store = await _hub()
    row = store["contacted"].get(str(user.id)) or {
        "name": str(user), "username": getattr(user, "name", ""), "count": 0, "in": 0, "out": 0, "last": 0,
    }
    row["name"] = getattr(user, "global_name", None) or getattr(user, "display_name", None) or str(user)
    row["username"] = getattr(user, "name", "") or row.get("username") or ""
    row["count"] = int(row.get("count") or 0) + 1
    row[direction] = int(row.get(direction) or 0) + 1
    row["last"] = int(_time.time())
    store["contacted"][str(user.id)] = row
    convo = store["convos"].get(str(user.id)) or {"owner": None, "log": []}
    convo["log"] = (convo.get("log") or [])[-80:]
    convo["log"].append({"dir": direction, "text": (text or "")[:500], "at": row["last"]})
    store["convos"][str(user.id)] = convo
    await _save_store()
    return store


def _people(store):
    rows = sorted((store.get("contacted") or {}).items(), key=lambda item: item[1].get("last") or 0, reverse=True)
    outbound = [(uid, row) for uid, row in rows if int(row.get("out") or 0) > 0]
    inbound = [(uid, row) for uid, row in rows if int(row.get("in") or 0) > 0]
    if not outbound and not inbound:
        outbound = rows
    return outbound, inbound


def _choice(uid, row):
    name = (row.get("name") or "Unknown")[:100]
    username = row.get("username") or ""
    return discord.SelectOption(
        label=name,
        description=(f"@{username}"[:100] if username else None),
        value=str(uid)[:100],
    )


def _transcript(uid, row, store):
    name = row.get("name") or uid
    log = ((store.get("convos") or {}).get(str(uid)) or {}).get("log") or []
    lines = []
    for entry in log[-18:]:
        who = "Bot" if entry.get("dir") == "out" else name
        when = entry.get("at")
        stamp = f"<t:{int(when)}:t> " if when else ""
        lines.append(f"{stamp}**{who}:** {(entry.get('text') or '')[:180]}")
    return "\n".join(lines) or "_No messages saved._"


def _history_embed(uid, row, store):
    name = row.get("name") or uid
    username = row.get("username")
    title = f"{name} (@{username})" if username else str(name)
    embed = discord.Embed(title="Messages", description=_transcript(uid, row, store)[:4000], color=0x5865F2)
    embed.set_author(name=title[:256])
    embed.add_field(name="Bot sent", value=str(int(row.get("out") or 0)), inline=True)
    embed.add_field(name="They sent", value=str(int(row.get("in") or 0)), inline=True)
    last = row.get("last")
    embed.add_field(name="Last", value=f"<t:{int(last)}:R>" if last else "—", inline=True)
    embed.add_field(name="User ID", value=f"`{uid}`", inline=False)
    embed.set_footer(text="Reply goes to this person only.")
    return embed


class PersonPick(discord.ui.Select):
    def __init__(self, people, placeholder, custom_id):
        super().__init__(
            placeholder=placeholder[:150],
            min_values=1,
            max_values=1,
            options=[_choice(uid, row) for uid, row in people[:25]],
            custom_id=custom_id,
        )

    async def callback(self, interaction: discord.Interaction):
        await _open_person(interaction, self.values[0])


class ReplyPerson(discord.ui.Button):
    def __init__(self, uid, name):
        super().__init__(label=f"Reply to {(name or 'them')[:40]}", style=discord.ButtonStyle.primary, custom_id=f"dm:reply:{uid}")
        self.uid = str(uid)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DmReplyModal(self.uid))


def _dmlist_view(store, selected=None):
    outbound, inbound = _people(store)
    people = list({uid: row for uid, row in outbound + inbound}.items())
    people.sort(key=lambda item: item[1].get("last") or 0, reverse=True)
    view = discord.ui.View(timeout=300)
    if people:
        view.add_item(PersonPick(people[:25], "Make a selection", "dmlist:pick"))
    if selected:
        row = (store.get("contacted") or {}).get(str(selected)) or {}
        view.add_item(ReplyPerson(selected, row.get("name")))
    return view


async def _open_person(interaction: discord.Interaction, uid: str):
    if not interaction.response.is_done():
        await interaction.response.defer()
    store = await _hub()
    row = (store.get("contacted") or {}).get(str(uid))
    if not row:
        await interaction.followup.send("That person isn't in the DM list.", ephemeral=True)
        return
    embed = _history_embed(uid, row, store)
    view = _dmlist_view(store, uid)
    await interaction.edit_original_response(content="Make a selection", embed=embed, view=view)


class DmReplyModal(discord.ui.Modal, title="Reply"):
    text = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, required=True, max_length=2000)

    def __init__(self, user_id: str):
        super().__init__(custom_id=f"dm:modal:{user_id}")
        self.user_id = str(user_id)

    async def on_submit(self, interaction: discord.Interaction):
        await _deliver_dm(interaction, self.user_id, str(self.text.value).strip(), None)


async def _deliver_dm(interaction: discord.Interaction, user_id: str, text: str, attachment):
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    async def _tell(content=None, embed=None):
        await interaction.followup.send(content=content, embed=embed, ephemeral=True)

    try:
        person = await interaction.client.fetch_user(int(user_id))
    except Exception:
        await _tell("That user ID doesn't exist.")
        return
    if not text and attachment is None:
        await _tell("Type a message.")
        return
    try:
        payload = {"allowed_mentions": discord.AllowedMentions.none()}
        if text:
            payload["content"] = text[:2000]
        if attachment is not None:
            payload["file"] = attachment
        await person.send(**payload)
    except discord.HTTPException as exc:
        reason = "Couldn't send that DM."
        if exc.code == 50007:
            reason = "I can't DM that person. Their DMs are closed, or they blocked the bot."
        elif exc.code == 50278:
            reason = "The bot isn't in a server with that person, so Discord won't let it DM them."
        await _tell(reason)
        return
    store = await _hub()
    convo = store["convos"].get(str(person.id)) or {"owner": None, "log": []}
    convo["owner"] = str(interaction.user.id)
    store["convos"][str(person.id)] = convo
    await _save_store()
    await _remember(person, text or "file", "out")
    embed = discord.Embed(title="Sent", description=(text or "File")[:500], color=0x34C759)
    embed.add_field(name="To", value=f"{person}\n`{person.id}`")
    embed.set_footer(text="If they reply, it comes to your DMs.")
    await _tell(embed=embed)


class SaySend(discord.ui.View):
    def __init__(self, text, raw, filename, channel_id):
        super().__init__(timeout=180)
        self.text = text
        self.raw = raw
        self.filename = filename
        self.channel_id = int(channel_id)
        self.owner_id = None
        self.token = None

    def _file(self):
        if not self.raw:
            return None
        return discord.File(_io.BytesIO(self.raw), filename=self.filename or "file")

    async def interaction_check(self, interaction: discord.Interaction):
        if self.owner_id and interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Send", style=discord.ButtonStyle.primary)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        kwargs = {"allowed_mentions": discord.AllowedMentions.none()}
        if self.text:
            kwargs["content"] = self.text[:2000]
        channel = interaction.client.get_channel(self.channel_id)
        if channel is not None:
            try:
                sent = self._file()
                call = channel.send(file=sent, **kwargs) if sent else channel.send(**kwargs)
                await asyncio.wait_for(call, timeout=1.5)
                await interaction.response.edit_message(content="Sent 1 message publicly", attachments=[], view=None)
                return
            except Exception as exc:
                _log(f"[say] {exc}")
        if interaction.response.is_done():
            return
        sent = self._file()
        payload = dict(kwargs)
        if sent:
            payload["file"] = sent
        await interaction.response.send_message(**payload)
        try:
            route = discord.http.Route(
                "PATCH",
                "/webhooks/{application_id}/{interaction_token}/messages/@original",
                application_id=APP_ID or interaction.application_id,
                interaction_token=self.token,
            )
            await interaction.client.http.request(
                route, json={"content": "Sent 1 message publicly", "components": [], "attachments": []}
            )
        except Exception as exc:
            _log(f"[say-edit] {exc}")


@tree.command(name="say", description="Post a message as the bot. Only you see it until you press Send.")
@app_commands.describe(
    message="The text to post. Type \\n to start a new line.",
    image="A picture to post with the text.",
    channel_id="Channel ID to post in. Leave empty to use this channel.",
)
async def say_cmd(
    interaction: discord.Interaction,
    message: Optional[str] = None,
    image: Optional[discord.Attachment] = None,
    channel_id: Optional[str] = None,
):
    text = (message or "").replace("\\n", "\n").strip()
    if not text and image is None:
        await interaction.response.send_message("Type something or add a picture.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    raw = await image.read() if image is not None else None
    target = _re.sub(r"\D", "", channel_id or "") or _opt(interaction, "channel") or interaction.channel_id
    view = SaySend(text or None, raw, image.filename if image else None, target)
    view.owner_id = interaction.user.id
    view.token = interaction.token
    payload = {"view": view, "ephemeral": True}
    if text:
        payload["content"] = text
    if raw:
        payload["file"] = discord.File(_io.BytesIO(raw), filename=image.filename)
    await interaction.followup.send(**payload)


def _clip(text: str, limit: int = 1990) -> str:
    return text[:limit]


def _chaos_static() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*_+-=[]{}:;<>?/|~"
    lines = []
    while sum(len(line) + 1 for line in lines) < 1880:
        lines.append("".join(_random.choice(alphabet) for _ in range(_random.randint(28, 72))))
    return _clip("\n".join(lines))


def _chaos_glitch() -> str:
    base = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    marks = [chr(code) for code in range(0x0300, 0x036F)]
    chunks = []
    while sum(len(part) for part in chunks) < 1700:
        char = _random.choice(base)
        chunks.append(char + "".join(_random.choice(marks) for _ in range(_random.randint(1, 3))))
        if _random.random() < 0.08:
            chunks.append("\n")
    return _clip("".join(chunks))


def _chaos_binary() -> str:
    lines = []
    while sum(len(line) + 1 for line in lines) < 1880:
        groups = [" ".join(f"{_random.randint(0, 255):08b}" for _ in range(4)) for _ in range(2)]
        lines.append("  ".join(groups))
    return _clip("\n".join(lines))


def _chaos_hex() -> str:
    offset = _random.randint(0x10000000, 0xE0000000)
    lines = []
    while sum(len(line) + 1 for line in lines) < 1880:
        data = [_random.randint(0, 255) for _ in range(16)]
        hexs = " ".join(f"{item:02X}" for item in data)
        shown = "".join(chr(item) if 32 <= item < 127 else "." for item in data)
        lines.append(f"{offset:08X}  {hexs}  |{shown}|")
        offset += 16
    return _clip("\n".join(lines))


def _chaos_blocks() -> str:
    chars = " ░▒▓█▄▀▌▐"
    lines = []
    while sum(len(line) + 1 for line in lines) < 1880:
        lines.append("".join(_random.choice(chars) for _ in range(_random.randint(24, 48))))
    return _clip("\n".join(lines))


def _chaos_wide() -> str:
    plain = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    lines = []
    while sum(len(line) + 1 for line in lines) < 1500:
        raw = "".join(_random.choice(plain) for _ in range(_random.randint(12, 28)))
        wide = []
        for char in raw:
            if "A" <= char <= "Z":
                wide.append(chr(0xFF21 + ord(char) - 65))
            elif "a" <= char <= "z":
                wide.append(chr(0xFF41 + ord(char) - 97))
            else:
                wide.append(chr(0xFF10 + ord(char) - 48))
        lines.append("".join(wide))
    return _clip("\n".join(lines))


def _chaos_boxes() -> str:
    chars = "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬╱╲╳╭╮╯╰"
    lines = []
    while sum(len(line) + 1 for line in lines) < 1880:
        lines.append("".join(_random.choice(chars) for _ in range(_random.randint(20, 42))))
    return _clip("\n".join(lines))


def _chaos_corrupt() -> str:
    tags = ("FAULT", "SEGV", "PANIC", "HEAP", "STACK", "ABORT", "NULL", "TRACE", "WATCH", "OVERFLOW")
    junk = "0123456789abcdef"
    lines = []
    addr = _random.randint(0x0000000010000000, 0x00000000F0000000)
    while sum(len(line) + 1 for line in lines) < 1880:
        tag = _random.choice(tags)
        blob = "".join(_random.choice(junk) for _ in range(_random.randint(24, 64)))
        lines.append(f"0x{addr:016x}  {tag:<9} {blob}")
        addr += _random.choice((16, 32, 64, 128, 4096))
    return _clip("\n".join(lines))


_CHAOS = {
    "static": ("Static burst", _chaos_static),
    "glitch": ("Zalgo glitch", _chaos_glitch),
    "binary": ("Binary stream", _chaos_binary),
    "hex": ("Hex dump", _chaos_hex),
    "blocks": ("Shade blocks", _chaos_blocks),
    "wide": ("Fullwidth", _chaos_wide),
    "boxes": ("Box fracture", _chaos_boxes),
    "corrupt": ("Memory corrupt", _chaos_corrupt),
}


def _chaos_text(style: str) -> str:
    builder = _CHAOS.get(style, _CHAOS["static"])[1]
    return _clip(builder())


class ChaosSend(discord.ui.View):
    def __init__(self, style: str, times: int, channel_id):
        super().__init__(timeout=180)
        self.style = style
        self.times = times
        self.channel_id = int(channel_id)
        self.owner_id = None
        self.token = None

    async def interaction_check(self, interaction: discord.Interaction):
        if self.owner_id and interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't yours.", ephemeral=True)
            return False
        return True

    async def _mark(self, interaction: discord.Interaction, text: str):
        try:
            route = discord.http.Route(
                "PATCH",
                "/webhooks/{application_id}/{interaction_token}/messages/@original",
                application_id=APP_ID or interaction.application_id,
                interaction_token=self.token,
            )
            await interaction.client.http.request(route, json={"content": text, "components": [], "embeds": [], "attachments": []})
        except Exception as exc:
            _log(f"[chaos-edit] {exc}")

    @discord.ui.button(label="Send", style=discord.ButtonStyle.danger)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        word = "message" if self.times == 1 else "messages"
        channel = interaction.client.get_channel(self.channel_id)
        if channel is None:
            texts = [_chaos_text(self.style) for _ in range(self.times)]
            await interaction.response.send_message(texts[0], allowed_mentions=discord.AllowedMentions.none())
            for text in texts[1:]:
                await asyncio.sleep(0.55)
                await interaction.followup.send(text, allowed_mentions=discord.AllowedMentions.none())
            await self._mark(interaction, f"Sent {self.times} {word} publicly")
            return
        await interaction.response.edit_message(content=f"Sending {self.times} {word}...", embed=None, view=None)
        sent = 0
        for index in range(self.times):
            text = _chaos_text(self.style)
            try:
                await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
                sent += 1
            except discord.HTTPException as exc:
                if getattr(exc, "status", None) == 429:
                    await asyncio.sleep(1.6)
                    try:
                        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
                        sent += 1
                    except Exception as again:
                        _log(f"[chaos] {again}")
                        break
                else:
                    _log(f"[chaos] {exc}")
                    break
            except Exception as exc:
                _log(f"[chaos] {exc}")
                break
            if index + 1 < self.times:
                await asyncio.sleep(0.55)
        done = "message" if sent == 1 else "messages"
        try:
            await interaction.edit_original_response(content=f"Sent {sent} {done} publicly")
        except Exception as exc:
            _log(f"[chaos-edit] {exc}")


@tree.command(name="chaos", description="Post long random text. Only you see a sample until you press Send.")
@app_commands.describe(
    style="The look of the random text.",
    times="How many messages to post: 1, 5, or 10.",
    channel_id="Channel ID to post in. Leave empty to use this channel.",
)
@app_commands.choices(
    style=[app_commands.Choice(name=label, value=key) for key, (label, _builder) in _CHAOS.items()],
    times=[
        app_commands.Choice(name="1", value=1),
        app_commands.Choice(name="5", value=5),
        app_commands.Choice(name="10", value=10),
    ],
)
async def chaos_cmd(
    interaction: discord.Interaction,
    style: str,
    times: int,
    channel_id: Optional[str] = None,
):
    if style not in _CHAOS or times not in (1, 5, 10):
        await interaction.response.send_message("Pick a style and 1, 5, or 10.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    sample = _chaos_text(style)
    target = _re.sub(r"\D", "", channel_id or "") or _opt(interaction, "channel") or interaction.channel_id
    view = ChaosSend(style, times, target)
    view.owner_id = interaction.user.id
    view.token = interaction.token
    label = _CHAOS[style][0]
    embed = discord.Embed(
        title=label,
        description=f"Sends {times} different message{'s' if times != 1 else ''}. Only you can see this.",
        color=0xED4245,
    )
    await interaction.followup.send(content=sample, embed=embed, view=view, ephemeral=True)


_PING_STATUS = {
    "any": "Any",
    "online": "Online",
    "idle": "Idle",
    "dnd": "Do Not Disturb",
    "offline": "Offline",
}


def _member_status(member) -> str:
    status = getattr(member, "status", None)
    value = str(getattr(status, "value", status) or "offline")
    if value == "invisible":
        return "offline"
    return value


def _ping_line(user_id: int, note: str) -> str:
    line = f"<@{user_id}>"
    if note:
        line = f"{line} {note}"
    return line[:2000]


class PingSend(discord.ui.View):
    def __init__(self, lines, channel_id):
        super().__init__(timeout=180)
        self.lines = list(lines)
        self.channel_id = int(channel_id)
        self.owner_id = None
        self.token = None
        self.running = False
        self.stopped = False

    async def interaction_check(self, interaction: discord.Interaction):
        if self.owner_id and interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't yours.", ephemeral=True)
            return False
        return True

    async def _mark(self, interaction: discord.Interaction, text: str, view=None):
        try:
            route = discord.http.Route(
                "PATCH",
                "/webhooks/{application_id}/{interaction_token}/messages/@original",
                application_id=APP_ID or interaction.application_id,
                interaction_token=self.token,
            )
            body = {"content": text, "embeds": [], "attachments": []}
            body["components"] = [] if view is None else view.to_components()
            await interaction.client.http.request(route, json=body)
        except Exception as exc:
            _log(f"[ping-edit] {exc}")

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.running:
            await interaction.response.send_message("Already started.", ephemeral=True)
            return
        self.running = True
        button.disabled = True
        mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)
        count = len(self.lines)
        word = "ping" if count == 1 else "pings"
        channel = interaction.client.get_channel(self.channel_id)
        if channel is None:
            await interaction.response.send_message(self.lines[0], allowed_mentions=mentions)
            sent = 1
            for line in self.lines[1:]:
                if self.stopped:
                    break
                await asyncio.sleep(0.6)
                if self.stopped:
                    break
                await interaction.followup.send(line, allowed_mentions=mentions)
                sent += 1
            done = "ping" if sent == 1 else "pings"
            text = f"Stopped. Sent {sent} {done}." if self.stopped else f"Sent {sent} {done} publicly"
            await self._mark(interaction, text)
            return
        await interaction.response.edit_message(content=f"Sending 0/{count}...", embed=None, view=self)
        sent = 0
        for index, line in enumerate(self.lines):
            if self.stopped:
                break
            try:
                await channel.send(line, allowed_mentions=mentions)
                sent += 1
            except discord.HTTPException as exc:
                if getattr(exc, "status", None) == 429 and not self.stopped:
                    await asyncio.sleep(1.6)
                    try:
                        await channel.send(line, allowed_mentions=mentions)
                        sent += 1
                    except Exception as again:
                        _log(f"[ping] {again}")
                        break
                else:
                    _log(f"[ping] {exc}")
                    break
            except Exception as exc:
                _log(f"[ping] {exc}")
                break
            if self.stopped:
                break
            try:
                await interaction.edit_original_response(content=f"Sending {sent}/{count}...", view=self)
            except Exception:
                pass
            if index + 1 < count:
                await asyncio.sleep(0.6)
        done = "ping" if sent == 1 else "pings"
        text = f"Stopped. Sent {sent} {done}." if self.stopped else f"Sent {sent} {done} publicly"
        try:
            await interaction.edit_original_response(content=text, view=None)
        except Exception as exc:
            _log(f"[ping-edit] {exc}")

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def halt(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stopped = True
        if not self.running:
            await interaction.response.edit_message(content="Stopped.", embed=None, attachments=[], view=None)
            return
        if not interaction.response.is_done():
            await interaction.response.defer()


async def _preview_ping(interaction: discord.Interaction, lines, detail: str, channel_id):
    view = PingSend(lines, channel_id)
    view.owner_id = interaction.user.id
    view.token = interaction.token
    embed = discord.Embed(title="Ping", description=f"{detail}\nOnly you can see this. Press Start to post it. Stop cancels.", color=0x5865F2)
    preview = "\n".join(lines)
    if len(preview) > 1900:
        preview = preview[:1900]
    await interaction.followup.send(
        content=preview,
        embed=embed,
        view=view,
        ephemeral=True,
        allowed_mentions=discord.AllowedMentions.none(),
    )


async def _load_members(guild):
    from discord.state import ChunkRequest

    state = guild._state
    request = ChunkRequest(guild.id, guild.shard_id, state.loop, state._get_guild, cache=True)
    state._chunk_requests[request.nonce] = request
    await state.chunker(guild.id, limit=0, presences=True, nonce=request.nonce)
    return await asyncio.wait_for(request.wait(), timeout=30)


async def _random_ping_targets(interaction: discord.Interaction, status: str, times: int, channel_id):
    guild = interaction.guild
    if guild is None and channel_id:
        cached = interaction.client.get_channel(int(channel_id))
        guild = getattr(cached, "guild", None)
    if guild is None:
        return None, "Random pings only work in a server this bot is in."
    try:
        members = await _load_members(guild)
    except Exception as exc:
        _log(f"[ping] member load failed: {exc}")
        try:
            members = await asyncio.wait_for(guild.chunk(cache=True), timeout=25)
        except Exception as again:
            _log(f"[ping] chunk failed: {again}")
            members = list(guild.members)
    pool = [
        member
        for member in members
        if member is not None and not getattr(member, "bot", False) and (status == "any" or _member_status(member) == status)
    ]
    _log(f"[ping] loaded {len(members)} members, {len(pool)} match {status}")
    if not pool:
        if not members:
            return None, "This bot still can't see the member list. Wait a minute and try again."
        return None, f"Nobody in the member list is {_PING_STATUS[status].lower()}."
    if len(pool) >= times:
        chosen = _random.sample(pool, times)
    else:
        chosen = [_random.choice(pool) for _ in range(times)]
    detail = f"Random · {_PING_STATUS[status]} · {times} ping{'s' if times != 1 else ''} · {len(pool)} people match"
    return chosen, detail


ping_group = app_commands.Group(
    name="ping",
    description="Ping people. Only you see the preview until you press Send.",
)


@ping_group.command(name="user", description="Ping one person, from 1 to 30 times.")
@app_commands.describe(
    user="The person who gets pinged.",
    times="How many times to ping them. From 1 to 30.",
    text="Extra text after the ping. Leave empty for just the ping.",
    channel_id="Channel ID to post in. Leave empty to use this channel.",
)
async def ping_user_cmd(
    interaction: discord.Interaction,
    user: discord.User,
    times: app_commands.Range[int, 1, 30],
    text: Optional[str] = None,
    channel_id: Optional[str] = None,
):
    await interaction.response.defer(ephemeral=True)
    note = (text or "").replace("\\n", "\n").strip()
    target = _re.sub(r"\D", "", channel_id or "") or _opt(interaction, "channel") or interaction.channel_id
    lines = [_ping_line(user.id, note) for _ in range(int(times))]
    detail = f"{user} · {int(times)} time{'s' if int(times) != 1 else ''}"
    await _preview_ping(interaction, lines, detail, target)


@ping_group.command(name="random", description="Ping random people in this server, from 1 to 30 times.")
@app_commands.describe(
    times="How many pings to send. From 1 to 30.",
    status="Who to pick: any, online, idle, do not disturb, or offline.",
    text="Extra text after each ping. Leave empty for just the ping.",
    channel_id="Channel ID to post in. Leave empty to use this channel.",
)
@app_commands.choices(status=[app_commands.Choice(name=label, value=key) for key, label in _PING_STATUS.items()])
async def ping_random_cmd(
    interaction: discord.Interaction,
    times: app_commands.Range[int, 1, 30],
    status: str = "any",
    text: Optional[str] = None,
    channel_id: Optional[str] = None,
):
    if status not in _PING_STATUS:
        await interaction.response.send_message("Pick a status.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    note = (text or "").replace("\\n", "\n").strip()
    target = _re.sub(r"\D", "", channel_id or "") or _opt(interaction, "channel") or interaction.channel_id
    chosen, detail = await _random_ping_targets(interaction, status, int(times), target)
    if chosen is None:
        await interaction.followup.send(detail, ephemeral=True)
        return
    lines = [_ping_line(person.id, note) for person in chosen]
    await _preview_ping(interaction, lines, detail, target)


tree.add_command(ping_group)


@tree.command(name="reply", description="Reply to a message as the bot. Nobody sees that you used it.")
@app_commands.describe(
    to="The message link, or the message ID if it is in this channel.",
    message="The reply text. Type \\n to start a new line.",
    image="A picture to send with the reply.",
)
async def reply_cmd(
    interaction: discord.Interaction,
    to: str,
    message: Optional[str] = None,
    image: Optional[discord.Attachment] = None,
):
    ref = _parse_ref(to, interaction.channel_id)
    if not ref:
        await interaction.response.send_message("Paste a message link, or the message ID.", ephemeral=True)
        return
    text = (message or "").replace("\\n", "\n").strip()
    if not text and image is None:
        await interaction.response.send_message("Type something or add a picture.", ephemeral=True)
        return
    channel_id, message_id = ref
    await _post_quiet(interaction, text or None, channel_id, image, message_id)


class ReplyModal(discord.ui.Modal, title="Reply"):
    text = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph, required=True, max_length=2000)

    def __init__(self, message: discord.Message):
        super().__init__(custom_id=f"say:modal:{message.id}:{message.channel.id}")
        self.target_message = message.id
        self.target_channel = message.channel.id

    async def on_submit(self, interaction: discord.Interaction):
        await _post_quiet(interaction, str(self.text.value).strip(), self.target_channel, None, self.target_message)


@tree.context_menu(name="Reply")
async def reply_menu(interaction: discord.Interaction, message: discord.Message):
    await interaction.response.send_modal(ReplyModal(message))


@tree.command(name="fakeip", description="Show a fake network lookup. Only you see the person picker.")
async def fakeip_cmd(interaction: discord.Interaction):
    await interaction.response.send_message("Make a selection", view=FakeIpView(), ephemeral=True)


@tree.command(name="dm", description="Send a DM from the bot. If they reply, it comes back to you.")
@app_commands.describe(
    user="The person to message.",
    id="Their user ID, if they are not in the picker.",
    message="What the bot should send. Type \\n for a new line.",
    file="A file to send with the DM.",
)
async def dm_cmd(
    interaction: discord.Interaction,
    message: str,
    user: Optional[discord.User] = None,
    id: Optional[str] = None,
    file: Optional[discord.Attachment] = None,
):
    await interaction.response.defer(ephemeral=True)
    person = await _person(interaction, user, id)
    text = message.replace("\\n", "\n").strip()
    if person is None:
        await interaction.followup.send("Pick a person or paste their ID.", ephemeral=True)
        return
    if person.bot or person.id == interaction.user.id:
        await interaction.followup.send("Pick someone else.", ephemeral=True)
        return
    attachment = await _file_from(file) if file is not None else None
    await _deliver_dm(interaction, str(person.id), text, attachment)


@tree.command(name="dmreply", description="Pick someone from the DM list and send them a reply.")
async def dmreply_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    store = await _hub()
    outbound, inbound = _people(store)
    people = list({uid: row for uid, row in outbound + inbound}.items())
    if not people:
        await interaction.followup.send("No DMs yet.", ephemeral=True)
        return
    view = discord.ui.View(timeout=300)
    view.add_item(PersonPick(people[:25], "Make a selection", "dmreply:pick"))
    await interaction.followup.send("Make a selection", view=view, ephemeral=True)


@tree.command(name="dmlist", description="See everyone the bot has DMed, and everyone who has DMed the bot.")
async def dmlist_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    store = await _hub()
    outbound, inbound = _people(store)
    people = {uid: row for uid, row in outbound + inbound}
    if not people:
        await interaction.followup.send("No DMs yet.", ephemeral=True)
        return
    embed = discord.Embed(title="DM list", description="Make a selection.", color=0x5865F2)
    embed.set_footer(text=f"{len(people)} people")
    await interaction.followup.send("Make a selection", embed=embed, view=_dmlist_view(store), ephemeral=True)


@tree.command(name="inbox", description="Choose who gets a copy when someone messages the bot.")
@app_commands.describe(enabled="Turn it on or off. Leave empty to see if it is on.")
async def inbox_cmd(interaction: discord.Interaction, enabled: Optional[bool] = None):
    await interaction.response.defer(ephemeral=True)
    store = await _hub()
    mine = str(store.get("inbox")) == str(interaction.user.id)
    if enabled is None:
        embed = discord.Embed(title="Inbox", color=0x5865F2 if mine else 0x99AAB5)
        embed.description = "On. Anyone who DMs the bot is sent to you." if mine else "Off. Turn it on to get their messages."
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    if enabled:
        store["inbox"] = str(interaction.user.id)
        await _save_store()
        embed = discord.Embed(title="Inbox on", description="I'll DM you when someone messages the bot, with a Reply button.", color=0x34C759)
        await interaction.followup.send(embed=embed, ephemeral=True)
        return
    if not mine:
        await interaction.followup.send("Inbox isn't pointed at you.", ephemeral=True)
        return
    store["inbox"] = None
    await _save_store()
    await interaction.followup.send(embed=discord.Embed(title="Inbox off", color=0xED4245), ephemeral=True)


@client.event
async def on_message(message: discord.Message):
    if message.guild is not None or message.author.bot:
        return
    store = await _hub()
    text = (message.content or "").strip()
    files = [item.url for item in message.attachments]
    if files:
        text = (text + "\n" + "\n".join(files)).strip()
    if not text:
        text = "(empty message)"
    await _remember(message.author, text, "in")
    convo = (store.get("convos") or {}).get(str(message.author.id)) or {"owner": None, "log": []}
    owner_id = str(convo.get("owner") or store.get("inbox") or "1387643893641777244")
    if owner_id == str(message.author.id):
        return
    if str(convo.get("owner") or "") != owner_id:
        convo["owner"] = owner_id
        store["convos"][str(message.author.id)] = convo
        if not store.get("inbox"):
            store["inbox"] = owner_id
        await _save_store()
    try:
        owner = await client.fetch_user(int(owner_id))
        embed = discord.Embed(description=text[:4000], color=0x5865F2, timestamp=datetime.now(timezone.utc))
        embed.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        embed.set_thumbnail(url=message.author.display_avatar.url)
        embed.add_field(name="User", value=f"{message.author}\n`{message.author.id}`", inline=True)
        embed.add_field(name="When", value=f"<t:{int(_time.time())}:F>", inline=True)
        embed.set_footer(text="Tap Reply. It goes to this person only.")
        view = discord.ui.View(timeout=None)
        view.add_item(ReplyPerson(message.author.id, str(message.author)))
        await owner.send(embed=embed, view=view)
    except Exception as exc:
        _log(f"[inbox] {exc}")



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
