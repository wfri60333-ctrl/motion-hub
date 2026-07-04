"""
Iteration 5 backend tests — Prometheus obfuscator + HWID cooldown/lockout +
loader flows + per-command role gate + unified target_id + route ordering.

Run:
  pytest /app/backend/tests/test_iter5_prometheus_hwid_flows.py -v \
    --junitxml=/app/test_reports/pytest/iter5_prometheus_hwid.xml
"""
import os
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://admin-toolkit-36.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

SAMPLE_LUA = 'print("HELLO_FROM_TEST") for i=1,3 do print(i) end return true'


# ---------- session fixture ----------
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---------- test data holders (module-scoped) ----------
STATE = {
    "loader_id": None,
    "script_ids": [],
    "keys": [],  # (key_id, key)
}


# =========================================================
# 1. HEALTH
# =========================================================
def test_health(s):
    r = s.get(f"{API}/health", timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") is True


# =========================================================
# 2. PROMETHEUS OBFUSCATOR — light / medium / heavy
# =========================================================
@pytest.mark.parametrize("level,expected_preset", [
    ("light", "Weak"),
    ("medium", "Medium"),
    ("heavy", "Strong"),
])
def test_obfuscate_prometheus_engine(s, level, expected_preset):
    r = s.post(f"{API}/obfuscate", json={"code": SAMPLE_LUA, "level": level}, timeout=60)
    assert r.status_code == 200, f"{level}: {r.status_code} {r.text[:400]}"
    j = r.json()
    engine = j.get("engine", "")
    assert engine.startswith("prometheus ("), (
        f"FAIL for level={level}: expected engine to start with 'prometheus (' "
        f"but got '{engine}'. Full response keys: {list(j.keys())}"
    )
    assert expected_preset in engine, (
        f"level={level}: engine='{engine}' should include preset '{expected_preset}'"
    )
    assert j["output_bytes"] > j["source_bytes"], "obfuscated output should be larger"
    assert "output" in j and len(j["output"]) > 0


def test_obfuscate_empty_code_400(s):
    r = s.post(f"{API}/obfuscate", json={"code": "", "level": "light"}, timeout=15)
    assert r.status_code == 400


def test_obfuscate_invalid_level_400(s):
    r = s.post(f"{API}/obfuscate", json={"code": "print(1)", "level": "insane"}, timeout=15)
    assert r.status_code == 400


# =========================================================
# 3. BOT CONFIG — new fields
# =========================================================
def test_get_bot_config_has_new_fields(s):
    r = s.get(f"{API}/bot/config", timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "command_role_perms" in j, f"missing command_role_perms in {list(j.keys())}"
    assert isinstance(j["command_role_perms"], dict)
    assert "hwid_reset_cooldown_hours" in j
    assert isinstance(j["hwid_reset_cooldown_hours"], int)
    assert "hwid_mismatch_lockout" in j
    assert isinstance(j["hwid_mismatch_lockout"], int)


def test_put_bot_config_persists(s):
    payload = {
        "command_role_perms": {"moderation": ["111"], "protection": ["222"]},
        "hwid_reset_cooldown_hours": 1,
        "hwid_mismatch_lockout": 3,
    }
    r = s.put(f"{API}/bot/config", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json().get("ok") is True

    g = s.get(f"{API}/bot/config", timeout=15)
    assert g.status_code == 200
    j = g.json()
    assert j["command_role_perms"] == {"moderation": ["111"], "protection": ["222"]}, j["command_role_perms"]
    assert j["hwid_reset_cooldown_hours"] == 1
    assert j["hwid_mismatch_lockout"] == 3


# =========================================================
# 4. COMMAND LIST — new commands + updated whitelist desc
# =========================================================
def test_bot_commands_contains_new_ones(s):
    r = s.get(f"{API}/bot/commands", timeout=15)
    assert r.status_code == 200
    cmds = r.json().get("commands", [])
    assert len(cmds) >= 66, f"expected >=66 commands, got {len(cmds)}"
    names = {c["name"] for c in cmds}
    for req in ("forceresethwid", "unlockkey", "perms", "resethwid", "whitelist", "panel"):
        assert req in names, f"missing command '{req}' in {sorted(names)}"
    wl = next(c for c in cmds if c["name"] == "whitelist")
    assert "grant a role" in wl["description"].lower(), (
        f"/whitelist description doesn't mention 'grant a role': {wl['description']!r}"
    )


# =========================================================
# 5. LOADER FLOW (unified target_id — loader_id path)
# =========================================================
def test_create_loader(s):
    r = s.post(f"{API}/loaders", json={"name": "TEST_iter5_loader", "description": "iter5"}, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] and j["loader"]["id"]
    STATE["loader_id"] = j["loader"]["id"]


def test_loader_upload_uses_prometheus(s):
    assert STATE["loader_id"], "loader must exist"
    r = s.post(
        f"{API}/loaders/{STATE['loader_id']}/upload",
        json={"name": "aimbot_test", "slug": "aimbot", "level": "medium", "code": SAMPLE_LUA},
        timeout=60,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j.get("ok") is True
    assert "prometheus" in (j.get("engine") or "").lower(), (
        f"loader upload engine should contain 'prometheus', got {j.get('engine')!r}"
    )
    STATE["script_ids"].append(j["script"]["id"])


def test_loader_menu_stub(s):
    lid = STATE["loader_id"]
    r = s.get(f"{API}/loader/{lid}.lua", timeout=15)
    assert r.status_code == 200, r.text
    body = r.text
    assert "Menu Loader" in body, f"menu stub should mention 'Menu Loader'. Got: {body[:200]}"
    # Base URL should be reflected somewhere in the stub
    assert BASE_URL in body or "http" in body, "base url should appear in stub"


def test_loader_bundle_stub(s):
    lid = STATE["loader_id"]
    r = s.get(f"{API}/loader/{lid}/bundle.lua", timeout=15)
    assert r.status_code == 200, r.text
    body = r.text
    assert "Bundle for loader" in body, f"bundle stub should mention 'Bundle for loader'. Got: {body[:200]}"


def test_create_key_loader_scoped(s):
    lid = STATE["loader_id"]
    r = s.post(f"{API}/keys", json={"loader_id": lid, "note": "TEST_iter5_loader_key"}, timeout=15)
    assert r.status_code == 200, r.text
    j = r.json()
    k = j["key"]
    assert k["loader_id"] == lid
    assert k.get("script_id") in (None, "", False), f"script_id should be null, got {k.get('script_id')!r}"
    STATE["keys"].append((k["id"], k["key"]))


def test_verify_loader_key_success_and_hwid_mismatch(s):
    lid = STATE["loader_id"]
    _, key = STATE["keys"][0]
    # first verify — binds hwid=abc
    r = s.get(f"{API}/verify", params={"loader_id": lid, "slug": "aimbot", "key": key, "hwid": "abc"}, timeout=30)
    assert r.status_code == 200
    body = r.text
    assert not body.startswith("ERROR:"), f"expected obfuscated payload, got: {body[:300]}"
    assert len(body) > 100, "expected non-trivial obfuscated payload"

    # second verify with different hwid — mismatch
    r2 = s.get(f"{API}/verify", params={"loader_id": lid, "slug": "aimbot", "key": key, "hwid": "def"}, timeout=30)
    assert r2.status_code == 200
    assert "ERROR: HWID mismatch" in r2.text, f"expected 'ERROR: HWID mismatch', got: {r2.text[:200]}"


# =========================================================
# 6. USER HWID RESET COOLDOWN
# =========================================================
def test_user_reset_hwid_cooldown_flow(s):
    """With cooldown=1h (set in test_put_bot_config_persists), first call OK,
    second call returns 429. Then admin reset always succeeds."""
    # First, create a fresh script + key for isolation
    obf_r = s.post(f"{API}/obfuscate", json={"code": SAMPLE_LUA, "level": "light"}, timeout=60)
    assert obf_r.status_code == 200
    obf_out = obf_r.json()["output"]
    save = s.post(f"{API}/scripts", json={
        "name": "TEST_iter5_script_cooldown",
        "source": SAMPLE_LUA, "obfuscated": obf_out, "level": "light",
    }, timeout=15)
    assert save.status_code == 200
    script_id = save.json()["id"]
    STATE["script_ids"].append(script_id)

    keyres = s.post(f"{API}/keys", json={"script_id": script_id, "note": "TEST_cooldown"}, timeout=15)
    assert keyres.status_code == 200
    key_doc = keyres.json()["key"]
    key_id, key = key_doc["id"], key_doc["key"]
    STATE["keys"].append((key_id, key))

    # Bind hwid so a reset is meaningful
    v = s.get(f"{API}/verify", params={"script_id": script_id, "key": key, "hwid": "hw_orig"}, timeout=30)
    assert v.status_code == 200 and not v.text.startswith("ERROR:"), v.text[:200]

    # First user reset — should succeed
    r1 = s.post(f"{API}/keys/user/resethwid", json={"key": key}, timeout=15)
    assert r1.status_code == 200, f"first user reset should be 200, got {r1.status_code}: {r1.text}"
    assert r1.json().get("ok") is True

    # Second immediate reset — 429
    r2 = s.post(f"{API}/keys/user/resethwid", json={"key": key}, timeout=15)
    assert r2.status_code == 429, f"second reset should be 429 (cooldown active), got {r2.status_code}: {r2.text}"
    detail = r2.json().get("detail", "")
    assert "cooldown" in detail.lower(), f"expected 'cooldown' in detail, got: {detail!r}"

    # Admin reset — always OK (bypass)
    a = s.post(f"{API}/keys/{key_id}/resethwid", timeout=15)
    assert a.status_code == 200, f"admin reset failed: {a.status_code} {a.text}"
    assert a.json().get("ok") is True


def test_route_ordering_user_vs_admin(s):
    """POST /api/keys/user/resethwid must NOT be captured by /api/keys/{key_id}/resethwid.
    We assert this by checking the response is a 200 (cooldown may have been cleared)
    or 429 (cooldown active) or 404 (invalid key), but NEVER an admin-style
    generic 200 with {'ok': False, 'error': 'key not found'} shape from the admin route,
    AND the endpoint enforces cooldown semantics."""
    r = s.post(f"{API}/keys/user/resethwid", json={"key": "definitely-not-a-real-key-xxxxx"}, timeout=15)
    # Admin route would return 200 with {"ok": False, "error": "key not found"}
    # User route returns 404 with {"detail": "Invalid key"}
    assert r.status_code == 404, (
        f"user route should return 404 for invalid key (not the admin route's 200). "
        f"Got {r.status_code}: {r.text}"
    )
    j = r.json()
    assert "detail" in j and "invalid" in j["detail"].lower(), j


# =========================================================
# 7. AUTO-LOCKOUT
# =========================================================
def test_hwid_auto_lockout(s):
    # Set lockout=2
    put = s.put(f"{API}/bot/config", json={"hwid_mismatch_lockout": 2, "hwid_reset_cooldown_hours": 1}, timeout=15)
    assert put.status_code == 200

    # Fresh script + key
    obf = s.post(f"{API}/obfuscate", json={"code": SAMPLE_LUA, "level": "light"}, timeout=60).json()["output"]
    sc = s.post(f"{API}/scripts", json={
        "name": "TEST_iter5_lockout_script",
        "source": SAMPLE_LUA, "obfuscated": obf, "level": "light",
    }, timeout=15).json()["id"]
    STATE["script_ids"].append(sc)
    kres = s.post(f"{API}/keys", json={"script_id": sc, "note": "TEST_lockout"}, timeout=15).json()["key"]
    key_id, key = kres["id"], kres["key"]
    STATE["keys"].append((key_id, key))

    # Bind hwid=v1
    v1 = s.get(f"{API}/verify", params={"script_id": sc, "key": key, "hwid": "v1"}, timeout=30)
    assert v1.status_code == 200 and not v1.text.startswith("ERROR:"), v1.text[:200]

    # Mismatch #1
    v2 = s.get(f"{API}/verify", params={"script_id": sc, "key": key, "hwid": "v2"}, timeout=30)
    assert "ERROR: HWID mismatch" in v2.text, v2.text[:200]

    # Mismatch #2 — should trigger lock (with lockout=2)
    v3 = s.get(f"{API}/verify", params={"script_id": sc, "key": key, "hwid": "v3"}, timeout=30)
    assert "locked" in v3.text.lower(), f"expected lockout, got: {v3.text[:200]}"

    # Subsequent verify returns lock message
    v4 = s.get(f"{API}/verify", params={"script_id": sc, "key": key, "hwid": "v1"}, timeout=30)
    assert "locked" in v4.text.lower(), f"expected 'locked', got: {v4.text[:200]}"

    # /api/keys shows status='locked' for this key
    keys = s.get(f"{API}/keys", timeout=15).json()["keys"]
    row = next((k for k in keys if k["id"] == key_id), None)
    assert row is not None, "test key must be in list"
    assert row["status"] == "locked", f"key status should be 'locked', got {row['status']!r}"

    # Admin reset unlocks
    a = s.post(f"{API}/keys/{key_id}/resethwid", timeout=15)
    assert a.status_code == 200
    keys2 = s.get(f"{API}/keys", timeout=15).json()["keys"]
    row2 = next(k for k in keys2 if k["id"] == key_id)
    assert row2["status"] == "active", f"after admin reset, status should be 'active', got {row2['status']!r}"


# =========================================================
# 8. KEY HISTORY + GLOBAL FEED
# =========================================================
def test_key_history_reverse_chronological(s):
    # Use the lockout key which has many events
    if not STATE["keys"]:
        pytest.skip("no key created yet")
    key_id, _ = STATE["keys"][-1]  # last one from lockout test
    r = s.get(f"{API}/keys/{key_id}/history", timeout=15)
    assert r.status_code == 200
    events = r.json().get("events", [])
    assert len(events) >= 3, f"expected >=3 events for lockout key, got {len(events)}: {events}"
    ts_list = [e.get("ts") for e in events if e.get("ts")]
    assert ts_list == sorted(ts_list, reverse=True), "events must be in reverse chronological order"
    event_names = {e.get("event") for e in events}
    # Expected at least these types
    for expected in ("hwid_bound", "verify_ok", "hwid_mismatch", "admin_reset"):
        assert expected in event_names, f"missing event {expected!r} in {event_names}"


def test_global_hwid_events_has_ip(s):
    r = s.get(f"{API}/hwid/events", params={"limit": 200}, timeout=15)
    assert r.status_code == 200
    events = r.json().get("events", [])
    assert len(events) > 0, "global feed should not be empty after verify runs"
    # At least one verify_ok or verify_* event should have an IP field attached
    with_ip = [e for e in events if e.get("ip")]
    assert with_ip, f"no events had 'ip' field attached. Sample: {events[:3]}"


# =========================================================
# 9. SCRIPT FLOW STILL WORKS
# =========================================================
def test_script_flow_end_to_end(s):
    obf = s.post(f"{API}/obfuscate", json={"code": SAMPLE_LUA, "level": "medium"}, timeout=60).json()
    assert obf.get("engine", "").startswith("prometheus (")
    save = s.post(f"{API}/scripts", json={
        "name": "TEST_iter5_script_e2e", "source": SAMPLE_LUA,
        "obfuscated": obf["output"], "level": "medium",
    }, timeout=15).json()
    sid = save["id"]
    STATE["script_ids"].append(sid)

    kres = s.post(f"{API}/keys", json={"script_id": sid, "note": "TEST_e2e"}, timeout=15).json()["key"]
    kid, key = kres["id"], kres["key"]
    STATE["keys"].append((kid, key))

    v = s.get(f"{API}/verify", params={"script_id": sid, "key": key, "hwid": "hw_e2e"}, timeout=30)
    assert v.status_code == 200
    body = v.text
    assert not body.startswith("ERROR:"), f"expected obfuscated payload, got: {body[:300]}"
    assert len(body) > 100
