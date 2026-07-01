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

from fastapi import FastAPI, APIRouter, HTTPException
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv
import uuid

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
    _push_log("[bot process exited]")
    BOT_RUNTIME["ready"] = False


def _is_bot_running() -> bool:
    return BOT_PROCESS is not None and BOT_PROCESS.poll() is None


@api_router.get("/")
async def root():
    return {"service": "discord-bot-control", "status": "ok"}


@api_router.get("/bot/config")
async def get_config():
    doc = await get_or_create_config()
    token = doc.get("bot_token") or ""
    doc["bot_token_masked"] = (
        (token[:6] + "•" * 10 + token[-4:]) if len(token) > 10 else ("•" * len(token))
    )
    doc["bot_token_set"] = bool(token)
    doc.pop("bot_token", None)
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
    global BOT_PROCESS, BOT_STARTED_AT, LOG_READER_TASK
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
    global BOT_PROCESS, BOT_STARTED_AT
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
    return {
        "commands": [
            {"name": "wipe", "description": "Delete every channel in this server.", "category": "moderation", "destructive": True, "status": "active"},
            {"name": "ban", "description": "Ban a member.", "category": "moderation", "status": "planned"},
            {"name": "kick", "description": "Kick a member.", "category": "moderation", "status": "planned"},
            {"name": "mute", "description": "Timeout a member.", "category": "moderation", "status": "planned"},
            {"name": "unmute", "description": "Remove a timeout.", "category": "moderation", "status": "planned"},
            {"name": "warn", "description": "Warn a member.", "category": "moderation", "status": "planned"},
            {"name": "purge", "description": "Bulk delete messages.", "category": "moderation", "status": "planned"},
            {"name": "lockdown", "description": "Lock a channel.", "category": "moderation", "status": "planned"},
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


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def _shutdown():
    if _is_bot_running():
        try:
            BOT_PROCESS.terminate()
        except Exception:
            pass
    client.close()
