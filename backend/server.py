"""
Discord Moderation Bot - Backend Control API
Manages the bot subprocess, config, logs, and audit trail.
"""
import os
import sys
import signal
import asyncio
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional
from collections import deque

from fastapi import FastAPI, APIRouter, HTTPException, Request
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv
import uuid

import re
from obfuscator import obfuscate as _obfuscate_lua

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

LOG_DIR = ROOT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
BOT_LOG_FILE = LOG_DIR / "bot.log"

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Discord Bot Control API")
api_router = APIRouter(prefix="/api")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bot_control")

LOG_BUFFER: deque = deque(maxlen=2000)
BOT_PROCESS: Optional[subprocess.Popen] = None
BOT_STARTED_AT: Optional[datetime] = None
LOG_READER_TASK: Optional[asyncio.Task] = None
AUTO_RESTART: bool = True  # flipped to False when user clicks Halt

BOT_RUNTIME = {
    "ready": False,
    "user": None,
    "guild_count": 0,
    "latency_ms": None,
}


class BotConfigUpdate(BaseModel):
    bot_token: Optional[str] = None
    application_id: Optional[str] = None
    allowed_role_ids: Optional[List[str]] = None
    luaobfuscator_api_key: Optional[str] = None


class AuditCreate(BaseModel):
    guild_id: str
    guild_name: str
    actor_id: str
    actor_name: str
    action: str
    details: dict = Field(default_factory=dict)


class RuntimeUpdate(BaseModel):
    ready: bool
    user: Optional[str] = None
    guild_count: int = 0
    latency_ms: Optional[float] = None


async def get_or_create_config() -> dict:
    doc = await db.bot_config.find_one({}, {"_id": 0})
    if not doc:
        doc = {
            "id": str(uuid.uuid4()),
            "bot_token": os.environ.get("DISCORD_BOT_TOKEN", ""),
            "application_id": os.environ.get("DISCORD_APP_ID", ""),
            "allowed_role_ids": [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.bot_config.insert_one(doc)
        doc.pop("_id", None)
    return doc


def _push_log(line: str):
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "line": line.rstrip(),
    }
    LOG_BUFFER.append(entry)
    # Also emit to stdout so it shows up in Render/Docker logs
    print(f"[bot] {entry['line']}", flush=True)
    try:
        with open(BOT_LOG_FILE, "a") as f:
            f.write(f"[{entry['ts']}] {entry['line']}\n")
    except Exception:
        pass


async def _read_bot_stdout(proc: subprocess.Popen):
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, proc.stdout.readline)
        if not line:
            break
        text = line.decode(errors="replace") if isinstance(line, bytes) else line
        _push_log(text)
    exit_code = proc.poll()
    _push_log(f"[bot process exited] code={exit_code}")
    BOT_RUNTIME["ready"] = False
    # Auto-restart unless user explicitly requested halt
    if AUTO_RESTART:
        await asyncio.sleep(3)
        _push_log("[control] auto-restart scheduled — relaunching bot")
        try:
            await bot_start()
        except Exception as e:
            _push_log(f"[control] auto-restart failed: {e}")


def _is_bot_running() -> bool:
    return BOT_PROCESS is not None and BOT_PROCESS.poll() is None


@api_router.api_route("/", methods=["GET", "HEAD"])
async def root():
    return {"service": "discord-bot-control", "status": "ok"}


@api_router.api_route("/health", methods=["GET", "HEAD"])
async def health():
    """Dedicated uptime-monitor endpoint. Accepts GET or HEAD."""
    return {"ok": True}


@api_router.get("/bot/config")
async def get_config():
    doc = await get_or_create_config()
    token = doc.get("bot_token") or ""
    doc["bot_token_masked"] = (
        (token[:6] + "•" * 10 + token[-4:]) if len(token) > 10 else ("•" * len(token))
    )
    doc["bot_token_set"] = bool(token)
    doc.pop("bot_token", None)
    lo = doc.get("luaobfuscator_api_key") or ""
    doc["luaobfuscator_api_key_masked"] = (
        (lo[:4] + "•" * 8 + lo[-4:]) if len(lo) > 8 else ("•" * len(lo))
    )
    doc["luaobfuscator_api_key_set"] = bool(lo)
    doc.pop("luaobfuscator_api_key", None)
    return doc


@api_router.put("/bot/config")
async def update_config(payload: BotConfigUpdate):
    current = await get_or_create_config()
    updates = {}
    if payload.bot_token is not None and payload.bot_token.strip():
        updates["bot_token"] = payload.bot_token.strip()
    if payload.application_id is not None:
        updates["application_id"] = payload.application_id.strip()
    if payload.allowed_role_ids is not None:
        updates["allowed_role_ids"] = [r.strip() for r in payload.allowed_role_ids if r.strip()]
    if payload.luaobfuscator_api_key is not None:
        updates["luaobfuscator_api_key"] = payload.luaobfuscator_api_key.strip()
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.bot_config.update_one({"id": current["id"]}, {"$set": updates})
    return {"ok": True}


@api_router.get("/bot/status")
async def bot_status():
    running = _is_bot_running()
    uptime = None
    if running and BOT_STARTED_AT:
        uptime = (datetime.now(timezone.utc) - BOT_STARTED_AT).total_seconds()
    return {
        "running": running,
        "pid": BOT_PROCESS.pid if running else None,
        "uptime_seconds": uptime,
        "runtime": BOT_RUNTIME,
        "started_at": BOT_STARTED_AT.isoformat() if BOT_STARTED_AT else None,
    }


@api_router.post("/bot/start")
async def bot_start():
    global BOT_PROCESS, BOT_STARTED_AT, LOG_READER_TASK, AUTO_RESTART
    AUTO_RESTART = True
    if _is_bot_running():
        return {"ok": True, "message": "Bot already running", "pid": BOT_PROCESS.pid}

    cfg = await get_or_create_config()
    token = (cfg.get("bot_token") or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Bot token is not configured")

    env = os.environ.copy()
    env["DISCORD_BOT_TOKEN"] = token
    env["DISCORD_APP_ID"] = cfg.get("application_id", "") or env.get("DISCORD_APP_ID", "")
    env["ALLOWED_ROLE_IDS"] = ",".join(cfg.get("allowed_role_ids") or [])
    env["BOT_API_URL"] = os.environ.get("BOT_API_URL", "http://localhost:8001")
    env["PYTHONUNBUFFERED"] = "1"

    bot_script = str(ROOT_DIR / "discord_bot.py")
    _push_log(f"[control] launching bot pid=... script={bot_script}")
    BOT_PROCESS = subprocess.Popen(
        [sys.executable, "-u", bot_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(ROOT_DIR),
    )
    BOT_STARTED_AT = datetime.now(timezone.utc)
    BOT_RUNTIME.update({"ready": False, "user": None, "guild_count": 0, "latency_ms": None})
    LOG_READER_TASK = asyncio.create_task(_read_bot_stdout(BOT_PROCESS))
    _push_log(f"[control] bot launched pid={BOT_PROCESS.pid}")
    return {"ok": True, "pid": BOT_PROCESS.pid}


@api_router.post("/bot/stop")
async def bot_stop():
    global BOT_PROCESS, BOT_STARTED_AT, AUTO_RESTART
    AUTO_RESTART = False  # user requested halt — do NOT auto-restart
    if not _is_bot_running():
        return {"ok": True, "message": "Bot is not running"}
    _push_log("[control] stopping bot")
    try:
        BOT_PROCESS.send_signal(signal.SIGTERM)
        try:
            BOT_PROCESS.wait(timeout=8)
        except subprocess.TimeoutExpired:
            BOT_PROCESS.kill()
    except Exception as e:
        _push_log(f"[control] error stopping bot: {e}")
    BOT_STARTED_AT = None
    BOT_RUNTIME.update({"ready": False, "user": None, "guild_count": 0, "latency_ms": None})
    return {"ok": True}


@api_router.get("/bot/logs")
async def bot_logs(since: int = 0, limit: int = 500):
    all_logs = list(LOG_BUFFER)
    total = len(all_logs)
    if since and since <= total:
        window = all_logs[since:]
    else:
        window = all_logs[-limit:]
    return {"cursor": total, "logs": window}


@api_router.delete("/bot/logs")
async def clear_logs():
    LOG_BUFFER.clear()
    try:
        BOT_LOG_FILE.write_text("")
    except Exception:
        pass
    return {"ok": True}


@api_router.get("/bot/commands")
async def list_commands():
    cmds = [
        # moderation
        ("wipe", "Delete every channel in this server.", "moderation", True),
        ("nuke", "Clone this channel and delete the original (wipes messages).", "moderation", True),
        ("ban", "Ban a member from the server.", "moderation", True),
        ("unban", "Unban a user by ID.", "moderation", False),
        ("kick", "Kick a member.", "moderation", True),
        ("timeout", "Timeout (mute) a member for a duration.", "moderation", False),
        ("untimeout", "Remove a timeout.", "moderation", False),
        ("warn", "Warn a member (persists in database).", "moderation", False),
        ("warnings", "Show warnings for a member.", "moderation", False),
        ("clearwarnings", "Delete all warnings for a member.", "moderation", False),
        ("purge", "Bulk delete recent messages.", "moderation", True),
        ("snipe", "Show last deleted message in this channel.", "moderation", False),
        ("banlist", "Show recent bans.", "moderation", False),
        # channel
        ("lock", "Lock this channel.", "channel", False),
        ("unlock", "Unlock this channel.", "channel", False),
        ("hide", "Hide this channel from @everyone.", "channel", False),
        ("show", "Reveal this channel.", "channel", False),
        ("slowmode", "Set channel slowmode.", "channel", False),
        ("rename", "Rename the current channel.", "channel", False),
        ("topic", "Set channel topic.", "channel", False),
        ("nsfw", "Toggle NSFW.", "channel", False),
        ("clone", "Clone this channel.", "channel", False),
        ("createchannel", "Create a new text channel.", "channel", False),
        ("deletechannel", "Delete a channel.", "channel", True),
        ("channelinfo", "Info about the current channel.", "channel", False),
        # role
        ("addrole", "Add a role to a member.", "role", False),
        ("removerole", "Remove a role from a member.", "role", False),
        ("createrole", "Create a role.", "role", False),
        ("deleterole", "Delete a role.", "role", True),
        ("rolecolor", "Change a role's color.", "role", False),
        ("roleinfo", "Info about a role.", "role", False),
        ("rolelist", "List all roles.", "role", False),
        # nickname
        ("nick", "Change a member's nickname.", "nickname", False),
        ("resetnick", "Reset a member's nickname.", "nickname", False),
        # voice
        ("vmute", "Voice-mute a member.", "voice", False),
        ("vunmute", "Voice-unmute a member.", "voice", False),
        ("deafen", "Server-deafen a member.", "voice", False),
        ("undeafen", "Un-deafen a member.", "voice", False),
        ("disconnect", "Disconnect from voice.", "voice", False),
        ("move", "Move to a voice channel.", "voice", False),
        # info
        ("ping", "Bot gateway latency.", "info", False),
        ("uptime", "Bot uptime.", "info", False),
        ("serverinfo", "Info about this server.", "info", False),
        ("userinfo", "Info about a member.", "info", False),
        ("avatar", "Show a user's avatar.", "info", False),
        ("membercount", "Total members.", "info", False),
        ("invites", "List active invites.", "info", False),
        # utility
        ("say", "Bot posts a message.", "utility", False),
        ("embed", "Post an embed.", "utility", False),
        ("poll", "Create a yes/no poll.", "utility", False),
        ("remind", "DM a reminder after a duration.", "utility", False),
        # emoji
        ("addemoji", "Add a custom emoji from URL.", "emoji", False),
        ("deleteemoji", "Delete a custom emoji.", "emoji", False),
        # config
        ("setmodlog", "Set the mod log channel.", "config", False),
        ("modlog", "Show mod log channel.", "config", False),
        ("autorole", "Set a role auto-added to new members.", "config", False),
        ("welcome", "Set a welcome channel.", "config", False),
        # script protection (native)
        ("panel", "Create your script panel with 5 buttons (Redeem/Get Script/Get Role/Reset HWID/Stats).", "protection", False),
        ("whitelist", "Generate a key for a user and DM it to them.", "protection", False),
        ("revoke", "Revoke a key (immediate).", "protection", True),
        ("resethwid", "Force-reset HWID for a key.", "protection", False),
        ("keyinfo", "Look up details of a key.", "protection", False),
    ]
    return {
        "commands": [
            {
                "name": n,
                "description": d,
                "category": cat,
                "destructive": destr,
                "status": "active",
            } for (n, d, cat, destr) in cmds
        ]
    }


@api_router.get("/bot/audit")
async def get_audit(limit: int = 100):
    rows = await db.audit_log.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return {"entries": rows}


@api_router.post("/bot/audit")
async def create_audit(payload: AuditCreate):
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["timestamp"] = datetime.now(timezone.utc).isoformat()
    await db.audit_log.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "id": doc["id"]}


@api_router.post("/bot/runtime")
async def update_runtime(payload: RuntimeUpdate):
    BOT_RUNTIME.update(payload.model_dump())
    return {"ok": True}


# ============= OBFUSCATION =============
class ObfuscateRequest(BaseModel):
    code: str
    level: str = "medium"  # light | medium | heavy


class SavedScriptCreate(BaseModel):
    name: str
    source: str
    obfuscated: str
    level: str
    note: Optional[str] = None


@api_router.post("/obfuscate")
async def obfuscate_endpoint(req: ObfuscateRequest):
    if not req.code or not req.code.strip():
        raise HTTPException(status_code=400, detail="Code cannot be empty")
    if req.level not in ("light", "medium", "heavy"):
        raise HTTPException(status_code=400, detail="Invalid level")
    cfg = await get_or_create_config()
    api_key = (cfg.get("luaobfuscator_api_key") or "").strip() or None
    try:
        out, engine = await _obfuscate_lua(req.code, req.level, api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Obfuscation failed: {e}")
    return {
        "ok": True,
        "level": req.level,
        "engine": engine,
        "source_bytes": len(req.code),
        "output_bytes": len(out),
        "output": out,
    }


@api_router.get("/scripts")
async def list_scripts():
    rows = await db.scripts.find({}, {"_id": 0, "source": 0, "obfuscated": 0}).sort(
        "created_at", -1
    ).to_list(200)
    return {"scripts": rows}


@api_router.get("/scripts/{script_id}")
async def get_script(script_id: str):
    doc = await db.scripts.find_one({"id": script_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@api_router.post("/scripts")
async def save_script(payload: SavedScriptCreate):
    doc = payload.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["source_bytes"] = len(payload.source)
    doc["output_bytes"] = len(payload.obfuscated)
    await db.scripts.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "id": doc["id"]}


@api_router.delete("/scripts/{script_id}")
async def delete_script(script_id: str):
    r = await db.scripts.delete_one({"id": script_id})
    return {"ok": True, "deleted": r.deleted_count}


# ============= SELF-HOSTED WHITELIST (mini-Luarmor) =============
import secrets as _secrets
from fastapi.responses import PlainTextResponse


class KeyCreate(BaseModel):
    script_id: Optional[str] = None
    loader_id: Optional[str] = None  # if set, key grants access to the whole loader
    discord_id: Optional[str] = None
    note: Optional[str] = None
    expires_days: Optional[int] = None


@api_router.post("/keys")
async def create_key(payload: KeyCreate):
    """Generate a whitelist key. Scope to a single script OR a whole loader."""
    if not payload.script_id and not payload.loader_id:
        raise HTTPException(status_code=400, detail="Provide either script_id or loader_id")
    script_name = None
    loader_name = None
    if payload.loader_id:
        loader = await db.loaders.find_one({"id": payload.loader_id}, {"_id": 0})
        if not loader:
            raise HTTPException(status_code=404, detail="Loader not found")
        loader_name = loader.get("name")
    if payload.script_id:
        script = await db.scripts.find_one({"id": payload.script_id}, {"_id": 0, "obfuscated": 0, "source": 0})
        if not script:
            raise HTTPException(status_code=404, detail="Script not found")
        script_name = script.get("name")
    now = datetime.now(timezone.utc)
    expires_at = None
    if payload.expires_days and payload.expires_days > 0:
        expires_at = (now + timedelta(days=int(payload.expires_days))).isoformat()
    doc = {
        "id": str(uuid.uuid4()),
        "key": _secrets.token_urlsafe(24),
        "script_id": payload.script_id or None,
        "script_name": script_name,
        "loader_id": payload.loader_id or None,
        "loader_name": loader_name,
        "discord_id": payload.discord_id or None,
        "note": payload.note or None,
        "hwid": None,
        "status": "active",
        "executions": 0,
        "created_at": now.isoformat(),
        "expires_at": expires_at,
        "last_used": None,
    }
    await db.wl_keys.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "key": doc}


@api_router.get("/keys")
async def list_keys():
    rows = await db.wl_keys.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return {"keys": rows}


@api_router.delete("/keys/{key_id}")
async def revoke_key(key_id: str):
    r = await db.wl_keys.delete_one({"id": key_id})
    return {"ok": True, "deleted": r.deleted_count}


@api_router.post("/keys/{key_id}/resethwid")
async def reset_key_hwid(key_id: str):
    r = await db.wl_keys.update_one({"id": key_id}, {"$set": {"hwid": None}})
    return {"ok": True, "modified": r.modified_count}


# --- Loader + verify (the actual execution flow) ---
from datetime import timedelta


# ============= LOADERS (grouping scripts under one product) =============
class LoaderCreate(BaseModel):
    name: str
    description: Optional[str] = None


class LoaderAddScript(BaseModel):
    script_id: str
    slug: str  # short name inside the loader, e.g. "aimbot", "esp"


@api_router.post("/loaders")
async def create_loader(payload: LoaderCreate):
    doc = {
        "id": str(uuid.uuid4()),
        "name": payload.name,
        "description": payload.description or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.loaders.insert_one(doc)
    doc.pop("_id", None)
    return {"ok": True, "loader": doc}


@api_router.get("/loaders")
async def list_loaders():
    loaders = await db.loaders.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Attach script listings
    for L in loaders:
        L["scripts"] = await db.scripts.find(
            {"loader_id": L["id"]},
            {"_id": 0, "obfuscated": 0, "source": 0},
        ).to_list(200)
    return {"loaders": loaders}


@api_router.delete("/loaders/{loader_id}")
async def delete_loader(loader_id: str):
    r = await db.loaders.delete_one({"id": loader_id})
    # Also detach scripts (don't delete them)
    await db.scripts.update_many({"loader_id": loader_id}, {"$unset": {"loader_id": "", "slug": ""}})
    return {"ok": True, "deleted": r.deleted_count}


@api_router.post("/loaders/{loader_id}/scripts")
async def add_script_to_loader(loader_id: str, payload: LoaderAddScript):
    loader = await db.loaders.find_one({"id": loader_id}, {"_id": 0})
    if not loader:
        raise HTTPException(status_code=404, detail="Loader not found")
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", payload.slug.strip().lower())[:32] or "script"
    # ensure unique slug within loader
    exists = await db.scripts.find_one({"loader_id": loader_id, "slug": slug}, {"_id": 0})
    if exists and exists["id"] != payload.script_id:
        raise HTTPException(status_code=400, detail=f"Slug '{slug}' already used in this loader")
    r = await db.scripts.update_one(
        {"id": payload.script_id},
        {"$set": {"loader_id": loader_id, "slug": slug}},
    )
    return {"ok": True, "modified": r.modified_count, "slug": slug}


@api_router.delete("/loaders/{loader_id}/scripts/{script_id}")
async def remove_script_from_loader(loader_id: str, script_id: str):
    r = await db.scripts.update_one(
        {"id": script_id, "loader_id": loader_id},
        {"$unset": {"loader_id": "", "slug": ""}},
    )
    return {"ok": True, "modified": r.modified_count}


import re as _re_module  # ensure re is available above (already imported at top)


@api_router.get("/loader/{script_id}.lua", response_class=PlainTextResponse)
async def get_loader_or_script(script_id: str, request: Request = None):
    """
    Universal loader endpoint. `script_id` can be:
      - a script's id (standalone mode, backward compatible)
      - a loader's id (menu mode — returns table with :load('slug') method)
    """
    base = str(request.base_url).rstrip("/") if request else "http://localhost:8001"
    # Check if it's a loader
    loader = await db.loaders.find_one({"id": script_id}, {"_id": 0})
    if loader:
        return _menu_loader_stub(loader, base)
    # Otherwise treat as standalone script
    script = await db.scripts.find_one({"id": script_id}, {"_id": 0, "obfuscated": 0, "source": 0})
    if not script:
        raise HTTPException(status_code=404, detail="Not found")
    return _standalone_loader_stub(script, base)


@api_router.get("/loader/{loader_id}/bundle.lua", response_class=PlainTextResponse)
async def get_loader_bundle(loader_id: str, request: Request = None):
    """All-in-one bundle mode: runs every script in the loader at once."""
    loader = await db.loaders.find_one({"id": loader_id}, {"_id": 0})
    if not loader:
        raise HTTPException(status_code=404, detail="Loader not found")
    base = str(request.base_url).rstrip("/") if request else "http://localhost:8001"
    scripts = await db.scripts.find(
        {"loader_id": loader_id},
        {"_id": 0, "obfuscated": 0, "source": 0},
    ).to_list(100)
    slugs = [s.get("slug") or s["id"] for s in scripts]
    return f"""-- MOD_CTRL Bundle for loader: {loader['name']}
if not script_key or #script_key < 8 then
    return warn("[MOD_CTRL] Set script_key before loading.")
end
local hwid = (gethwid and gethwid()) or (game and game:GetService("RbxAnalyticsService"):GetClientId()) or "unknown"
for _, slug in ipairs({{"{'","'.join(slugs)}"}}) do
    local url = "{base}/api/loader/{loader_id}/" .. slug .. ".lua"
    local body = game:HttpGet(url)
    if body:sub(1,6) == "ERROR:" then
        warn("[MOD_CTRL " .. slug .. "] " .. body)
    else
        local fn, err = loadstring(body)
        if fn then pcall(fn) else warn("[MOD_CTRL " .. slug .. "] " .. tostring(err)) end
    end
end
"""


@api_router.get("/loader/{loader_id}/{slug}.lua", response_class=PlainTextResponse)
async def get_loader_script(loader_id: str, slug: str, request: Request = None):
    """Individual-URL mode: each script under a loader has its own URL, shares the same key."""
    script = await db.scripts.find_one(
        {"loader_id": loader_id, "slug": slug},
        {"_id": 0, "obfuscated": 0, "source": 0},
    )
    if not script:
        raise HTTPException(status_code=404, detail="Script not found in loader")
    base = str(request.base_url).rstrip("/") if request else "http://localhost:8001"
    return _standalone_loader_stub(script, base, loader_id=loader_id, slug=slug)


def _standalone_loader_stub(script: dict, base: str, loader_id: str = None, slug: str = None) -> str:
    verify_qs = f"script_id={script['id']}"
    if loader_id:
        verify_qs += f"&loader_id={loader_id}"
    return f"""-- MOD_CTRL Loader for script: {script.get('name')}
if not script_key or #script_key < 8 then
    return warn("[MOD_CTRL] Set script_key before loading.")
end
local hwid = (gethwid and gethwid()) or (game and game:GetService("RbxAnalyticsService"):GetClientId()) or "unknown"
local url = "{base}/api/verify?{verify_qs}&key=" .. script_key .. "&hwid=" .. hwid
local body = game:HttpGet(url)
if body:sub(1, 6) == "ERROR:" then return warn("[MOD_CTRL] " .. body) end
local fn, err = loadstring(body)
if not fn then return warn("[MOD_CTRL] load failed: " .. tostring(err)) end
return fn()
"""


def _menu_loader_stub(loader: dict, base: str) -> str:
    """Menu-mode loader — returns a table with :load(slug) method."""
    return f"""-- MOD_CTRL Menu Loader: {loader['name']}
-- Usage:
--   script_key = "YOUR_KEY"
--   local Yuna = loadstring(game:HttpGet(".../api/loader/{loader['id']}.lua"))()
--   Yuna:load("aimbot")
if not script_key or #script_key < 8 then
    warn("[MOD_CTRL] Set script_key before using this loader.")
end
local L = {{ __key = script_key, __loader = "{loader['id']}", __base = "{base}" }}
function L:load(slug)
    if not script_key or #script_key < 8 then return warn("[MOD_CTRL] Missing script_key.") end
    local hwid = (gethwid and gethwid()) or (game and game:GetService("RbxAnalyticsService"):GetClientId()) or "unknown"
    local url = self.__base .. "/api/verify?loader_id=" .. self.__loader .. "&slug=" .. slug ..
                "&key=" .. script_key .. "&hwid=" .. hwid
    local body = game:HttpGet(url)
    if body:sub(1,6) == "ERROR:" then return warn("[MOD_CTRL " .. slug .. "] " .. body) end
    local fn, err = loadstring(body)
    if not fn then return warn("[MOD_CTRL " .. slug .. "] " .. tostring(err)) end
    return fn()
end
function L:bundle()
    return loadstring(game:HttpGet(self.__base .. "/api/loader/" .. self.__loader .. "/bundle.lua"))()
end
return L
"""


@api_router.get("/verify", response_class=PlainTextResponse)
async def verify_key(script_id: Optional[str] = None, loader_id: Optional[str] = None,
                     slug: Optional[str] = None, key: str = "", hwid: str = ""):
    """Called by the loader. Verifies key + HWID.
    Accepts either script_id (standalone) or loader_id + optional slug (loader mode).
    """
    if not key:
        return "ERROR: missing key"
    # Resolve target script
    target = None
    if loader_id:
        if slug:
            target = await db.scripts.find_one({"loader_id": loader_id, "slug": slug}, {"_id": 0})
        # Also allow key lookup by loader_id (any key linked to this loader)
        row = await db.wl_keys.find_one({"key": key, "loader_id": loader_id}, {"_id": 0})
        if not row:
            # backward-compat: also check keys with just script_id if slug script has it
            if target:
                row = await db.wl_keys.find_one({"key": key, "script_id": target["id"]}, {"_id": 0})
    else:
        target = await db.scripts.find_one({"id": script_id}, {"_id": 0}) if script_id else None
        row = await db.wl_keys.find_one({"key": key, "script_id": script_id}, {"_id": 0}) if script_id else None
    if not row:
        return "ERROR: invalid key"
    if row.get("status") != "active":
        return "ERROR: key is not active"
    exp = row.get("expires_at")
    if exp:
        try:
            if datetime.fromisoformat(exp) < datetime.now(timezone.utc):
                return "ERROR: key expired"
        except Exception:
            pass
    stored_hwid = row.get("hwid")
    if stored_hwid and hwid and stored_hwid != hwid:
        return "ERROR: HWID mismatch. Ask admin to reset."
    if not stored_hwid and hwid:
        await db.wl_keys.update_one({"key": key}, {"$set": {"hwid": hwid}})
    await db.wl_keys.update_one(
        {"key": key},
        {"$inc": {"executions": 1},
         "$set": {"last_used": datetime.now(timezone.utc).isoformat()}},
    )
    if not target:
        return "ERROR: target script not found"
    payload = await db.scripts.find_one({"id": target["id"]}, {"_id": 0})
    return payload.get("obfuscated") or "ERROR: no payload"


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup_autoboot():
    """Auto-launch the bot whenever the backend starts, if a token is configured."""
    async def _boot():
        try:
            await asyncio.sleep(1.5)  # allow mongo/motor to warm up
            cfg = await get_or_create_config()
            if (cfg.get("bot_token") or "").strip():
                _push_log("[control] backend boot — auto-starting bot")
                await bot_start()
            else:
                _push_log("[control] backend boot — no token configured, skipping auto-start")
        except Exception as e:
            _push_log(f"[control] auto-start on boot failed: {e}")
    asyncio.create_task(_boot())


@app.on_event("shutdown")
async def _shutdown():
    global AUTO_RESTART
    AUTO_RESTART = False
    if _is_bot_running():
        try:
            BOT_PROCESS.terminate()
        except Exception:
            pass
    client.close()
