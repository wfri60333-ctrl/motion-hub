"""Backend API tests for Discord bot control dashboard."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://admin-toolkit-36.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---------- health ----------
def test_health_root(s):
    r = s.get(f"{API}/")
    assert r.status_code == 200
    d = r.json()
    assert d.get("service") == "discord-bot-control"
    assert d.get("status") == "ok"


# ---------- config ----------
def test_config_masked_and_flags(s):
    r = s.get(f"{API}/bot/config")
    assert r.status_code == 200
    d = r.json()
    assert d.get("bot_token_set") is True
    assert "bot_token_masked" in d
    assert "bot_token" not in d  # raw token should never leak
    # user provided app id from problem statement
    assert d.get("application_id") == "1521654504045543578"
    # masked token should begin with first 6 chars of the seed token
    assert d["bot_token_masked"].startswith("dfXwYU")


def test_config_update_preserves_token(s):
    # snapshot
    before = s.get(f"{API}/bot/config").json()
    original_masked = before["bot_token_masked"]

    # Send empty bot_token - must NOT overwrite existing token
    payload = {
        "bot_token": "",
        "application_id": "1521654504045543578",
        "allowed_role_ids": ["111111111111111111", "222222222222222222"],
    }
    r = s.put(f"{API}/bot/config", json=payload)
    assert r.status_code == 200
    assert r.json().get("ok") is True

    after = s.get(f"{API}/bot/config").json()
    assert after["bot_token_set"] is True
    assert after["bot_token_masked"] == original_masked  # token preserved
    assert after["application_id"] == "1521654504045543578"
    assert after["allowed_role_ids"] == ["111111111111111111", "222222222222222222"]

    # revert roles to empty for clean state
    s.put(f"{API}/bot/config", json={"allowed_role_ids": []})


# ---------- status / start / stop / logs ----------
def test_initial_status(s):
    # Ensure stopped state first
    s.post(f"{API}/bot/stop")
    time.sleep(1)
    r = s.get(f"{API}/bot/status")
    assert r.status_code == 200
    d = r.json()
    assert d.get("running") is False
    assert d.get("runtime", {}).get("ready") is False


def test_clear_logs(s):
    r = s.delete(f"{API}/bot/logs")
    assert r.status_code == 200
    assert r.json().get("ok") is True
    logs = s.get(f"{API}/bot/logs").json()
    assert logs["logs"] == []
    assert logs["cursor"] == 0


def test_start_bot_and_invalid_token_flow(s):
    # ensure stopped and logs clean
    s.post(f"{API}/bot/stop")
    time.sleep(1)
    s.delete(f"{API}/bot/logs")

    r = s.post(f"{API}/bot/start")
    assert r.status_code == 200
    d = r.json()
    assert d.get("ok") is True
    assert d.get("pid")

    # Second call - already running message
    r2 = s.post(f"{API}/bot/start")
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2.get("ok") is True
    # Might be "already running" or new pid depending on timing; accept either
    # but if the process is still alive we expect the "already running" branch
    # (bot has not yet exited)
    # We won't hard-assert the message text to avoid flakiness.

    # Wait for the invalid-token bot to boot up and fail
    time.sleep(8)

    logs = s.get(f"{API}/bot/logs").json()
    joined = "\n".join(l["line"] for l in logs["logs"])
    assert "[boot]" in joined, f"Missing [boot] in logs:\n{joined}"
    # discord.py logs 'logging in using static token' via its logger
    assert "logging in using static token" in joined.lower(), \
        f"Missing 'logging in using static token':\n{joined}"
    assert "[fatal] login failed" in joined.lower(), \
        f"Missing [fatal] login failed:\n{joined}"

    # After the fatal exit, running should flip false
    time.sleep(2)
    st = s.get(f"{API}/bot/status").json()
    assert st["running"] is False
    assert st["runtime"]["ready"] is False


def test_stop_when_already_exited(s):
    r = s.post(f"{API}/bot/stop")
    assert r.status_code == 200
    assert r.json().get("ok") is True


# ---------- commands ----------
def test_commands_registry(s):
    r = s.get(f"{API}/bot/commands")
    assert r.status_code == 200
    d = r.json()
    assert "commands" in d
    cmds = d["commands"]
    assert isinstance(cmds, list)
    assert len(cmds) == 8
    wipe = next((c for c in cmds if c["name"] == "wipe"), None)
    assert wipe is not None
    assert wipe.get("destructive") is True
    assert wipe.get("status") == "active"


# ---------- audit ----------
def test_audit_create_and_list(s):
    entry = {
        "guild_id": "999000111",
        "guild_name": "TEST_guild",
        "actor_id": "42",
        "actor_name": "TEST_actor",
        "action": "wipe_channels",
        "details": {"deleted": 3, "failed": 0},
    }
    r = s.post(f"{API}/bot/audit", json=entry)
    assert r.status_code == 200
    d = r.json()
    assert d.get("ok") is True
    assert d.get("id")

    # Second entry to check sort order
    entry2 = dict(entry, guild_name="TEST_guild_2")
    s.post(f"{API}/bot/audit", json=entry2)

    lst = s.get(f"{API}/bot/audit").json()
    assert "entries" in lst
    rows = lst["entries"]
    assert len(rows) >= 2
    # sorted desc by timestamp
    ts_list = [r["timestamp"] for r in rows]
    assert ts_list == sorted(ts_list, reverse=True)
    # no _id key leaked
    for row in rows:
        assert "_id" not in row
