"""
MOD_CTRL — Backend integration tests for iteration 2.

Covers:
  * root health
  * bot status/config (masked, no luarmor references)
  * commands registry (62 commands, categories, no lm-*, protection cmds)
  * obfuscation (built-in engine)
  * scripts CRUD
  * loaders CRUD + attach flow
  * loader endpoints (menu, bundle, individual slug)
  * loader-scoped keys (verify, HWID lock, mismatch, reset)
"""
import os
import pytest
import requests

BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"


# ---------- shared session ----------
@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})
    return sess


# ---------- health ----------
def test_root_health(s):
    r = s.get(f"{API}/")
    assert r.status_code == 200
    d = r.json()
    assert d["service"] == "discord-bot-control"
    assert d["status"] == "ok"


# ---------- bot status ----------
def test_bot_status_shape(s):
    r = s.get(f"{API}/bot/status")
    assert r.status_code == 200
    d = r.json()
    assert "running" in d
    assert "runtime" in d
    assert "ready" in d["runtime"]
    # Note: review request expects running=True with valid Motion Hub#4800 token.
    # We do NOT hard-assert running here because the token stored in DB is
    # currently invalid (see test report). The endpoint contract itself is OK.


# ---------- config: no luarmor, luaobfuscator flags present ----------
def test_config_no_luarmor_and_lo_flags(s):
    r = s.get(f"{API}/bot/config")
    assert r.status_code == 200
    d = r.json()
    assert d.get("bot_token_set") is True
    assert "bot_token_masked" in d
    assert "bot_token" not in d
    # New LuaObfuscator surface
    assert "luaobfuscator_api_key_masked" in d
    assert "luaobfuscator_api_key_set" in d
    # Legacy Luarmor surface MUST be gone
    assert "luarmor_api_key" not in d
    assert "luarmor_api_key_masked" not in d
    assert "luarmor_api_key_set" not in d


# ---------- commands registry ----------
def test_commands_registry_62_and_categories(s):
    r = s.get(f"{API}/bot/commands")
    assert r.status_code == 200
    cmds = r.json()["commands"]
    assert isinstance(cmds, list)
    assert len(cmds) == 62, f"expected 62 commands, got {len(cmds)}"
    cats = {c["category"] for c in cmds}
    expected_cats = {
        "moderation", "channel", "role", "voice", "nickname",
        "info", "utility", "config", "emoji", "protection",
    }
    assert expected_cats.issubset(cats), f"missing categories: {expected_cats - cats}"


def test_commands_protection_five(s):
    cmds = s.get(f"{API}/bot/commands").json()["commands"]
    prot = {c["name"] for c in cmds if c["category"] == "protection"}
    assert prot == {"panel", "whitelist", "revoke", "resethwid", "keyinfo"}


def test_commands_no_luarmor_leftovers(s):
    cmds = s.get(f"{API}/bot/commands").json()["commands"]
    assert not any(c["name"].startswith("lm-") for c in cmds)
    assert not any(c["category"] == "luarmor" for c in cmds)


# ---------- obfuscation ----------
def test_obfuscate_builtin(s):
    r = s.post(f"{API}/obfuscate", json={"code": 'print("hi")', "level": "medium"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["engine"] == "built-in"
    assert d["source_bytes"] > 0
    assert d["output_bytes"] > 0
    assert isinstance(d["output"], str)
    assert len(d["output"]) > 0


def test_obfuscate_invalid_level(s):
    r = s.post(f"{API}/obfuscate", json={"code": 'print("x")', "level": "extreme"})
    assert r.status_code == 400


def test_obfuscate_empty_code(s):
    r = s.post(f"{API}/obfuscate", json={"code": "", "level": "medium"})
    assert r.status_code == 400


# ---------- scripts CRUD ----------
@pytest.fixture(scope="module")
def created_script_id(s):
    payload = {
        "name": "TEST_script_iter2",
        "source": 'print("hi")',
        "obfuscated": "OBF_PAYLOAD_A",
        "level": "medium",
        "note": "TEST",
    }
    r = s.post(f"{API}/scripts", json=payload)
    assert r.status_code == 200
    sid = r.json()["id"]
    yield sid
    s.delete(f"{API}/scripts/{sid}")


def test_scripts_list_contains_created(s, created_script_id):
    r = s.get(f"{API}/scripts")
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["scripts"]]
    assert created_script_id in ids


def test_scripts_get_full_doc(s, created_script_id):
    r = s.get(f"{API}/scripts/{created_script_id}")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == created_script_id
    assert d["obfuscated"] == "OBF_PAYLOAD_A"
    assert d["source"] == 'print("hi")'
    assert "_id" not in d


def test_scripts_delete_and_verify_gone(s):
    r = s.post(f"{API}/scripts", json={
        "name": "TEST_delete_me", "source": "x", "obfuscated": "y",
        "level": "light",
    })
    sid = r.json()["id"]
    r2 = s.delete(f"{API}/scripts/{sid}")
    assert r2.status_code == 200
    assert r2.json()["deleted"] == 1
    r3 = s.get(f"{API}/scripts/{sid}")
    assert r3.status_code == 404


# ---------- loaders CRUD + full attach flow ----------
@pytest.fixture(scope="module")
def loader_with_two_scripts(s):
    # Create loader
    r = s.post(f"{API}/loaders", json={"name": "TEST_loader_iter2"})
    assert r.status_code == 200
    lid = r.json()["loader"]["id"]

    # Save two scripts
    sids = []
    for i, payload_obf in enumerate([("script_a", "OBF_A"), ("script_b", "OBF_B")]):
        name, obf = payload_obf
        r2 = s.post(f"{API}/scripts", json={
            "name": f"TEST_{name}", "source": f"src_{i}",
            "obfuscated": obf, "level": "medium",
        })
        sids.append(r2.json()["id"])

    # Attach both to loader
    for sid, slug in zip(sids, ["a", "b"]):
        r3 = s.post(f"{API}/loaders/{lid}/scripts",
                    json={"script_id": sid, "slug": slug})
        assert r3.status_code == 200
        assert r3.json()["slug"] == slug

    yield {"loader_id": lid, "script_ids": sids}

    # cleanup
    s.delete(f"{API}/loaders/{lid}")
    for sid in sids:
        s.delete(f"{API}/scripts/{sid}")


def test_loader_create_and_list_empty(s):
    r = s.post(f"{API}/loaders", json={"name": "TEST_empty_loader"})
    lid = r.json()["loader"]["id"]
    lst = s.get(f"{API}/loaders").json()["loaders"]
    matched = [x for x in lst if x["id"] == lid]
    assert matched, "empty loader missing in list"
    assert matched[0]["scripts"] == []
    s.delete(f"{API}/loaders/{lid}")


def test_loader_attach_and_list_shows_both(s, loader_with_two_scripts):
    lid = loader_with_two_scripts["loader_id"]
    loaders = s.get(f"{API}/loaders").json()["loaders"]
    L = next(x for x in loaders if x["id"] == lid)
    slugs = {x["slug"] for x in L["scripts"]}
    assert slugs == {"a", "b"}


# ---------- loader endpoints (Lua text) ----------
def test_loader_menu_lua(s, loader_with_two_scripts):
    lid = loader_with_two_scripts["loader_id"]
    r = s.get(f"{API}/loader/{lid}.lua")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")
    body = r.text
    assert "MOD_CTRL Menu Loader" in body
    assert ":load(" in body


def test_loader_bundle_lua(s, loader_with_two_scripts):
    lid = loader_with_two_scripts["loader_id"]
    r = s.get(f"{API}/loader/{lid}/bundle.lua")
    assert r.status_code == 200
    body = r.text
    assert "Bundle" in body


def test_loader_individual_slug_lua(s, loader_with_two_scripts):
    lid = loader_with_two_scripts["loader_id"]
    r = s.get(f"{API}/loader/{lid}/a.lua")
    assert r.status_code == 200
    body = r.text
    # standalone stub markers
    assert "MOD_CTRL Loader for script" in body
    assert "loadstring" in body


# ---------- loader-scoped keys + verify + HWID ----------
@pytest.fixture(scope="module")
def loader_key(s, loader_with_two_scripts):
    lid = loader_with_two_scripts["loader_id"]
    r = s.post(f"{API}/keys", json={"loader_id": lid, "note": "TEST"})
    assert r.status_code == 200
    doc = r.json()["key"]
    yield {"loader_id": lid, "key": doc["key"], "key_id": doc["id"]}
    s.delete(f"{API}/keys/{doc['id']}")


def test_verify_slug_a_returns_payload_a(s, loader_key):
    lid = loader_key["loader_id"]
    r = s.get(f"{API}/verify",
              params={"loader_id": lid, "slug": "a",
                      "key": loader_key["key"], "hwid": "hw1"})
    assert r.status_code == 200
    assert r.text == "OBF_A"


def test_verify_same_key_slug_b_returns_payload_b(s, loader_key):
    """Proves loader-wide key access."""
    lid = loader_key["loader_id"]
    r = s.get(f"{API}/verify",
              params={"loader_id": lid, "slug": "b",
                      "key": loader_key["key"], "hwid": "hw1"})
    assert r.status_code == 200
    assert r.text == "OBF_B"


def test_verify_hwid_mismatch(s, loader_key):
    lid = loader_key["loader_id"]
    r = s.get(f"{API}/verify",
              params={"loader_id": lid, "slug": "a",
                      "key": loader_key["key"], "hwid": "different"})
    assert r.status_code == 200
    assert r.text == "ERROR: HWID mismatch. Ask admin to reset."


def test_reset_hwid_allows_new_hwid(s, loader_key):
    kid = loader_key["key_id"]
    r = s.post(f"{API}/keys/{kid}/resethwid")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    # verify with a different hwid should now succeed
    lid = loader_key["loader_id"]
    r2 = s.get(f"{API}/verify",
               params={"loader_id": lid, "slug": "a",
                       "key": loader_key["key"], "hwid": "hw_new"})
    assert r2.status_code == 200
    assert r2.text == "OBF_A"


def test_verify_invalid_key(s, loader_with_two_scripts):
    lid = loader_with_two_scripts["loader_id"]
    r = s.get(f"{API}/verify",
              params={"loader_id": lid, "slug": "a",
                      "key": "bogus_key_that_does_not_exist", "hwid": "hw1"})
    assert r.status_code == 200
    assert r.text == "ERROR: invalid key"
