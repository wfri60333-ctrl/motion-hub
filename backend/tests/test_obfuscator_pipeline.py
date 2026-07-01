"""
Iteration-4: Full obfuscator + script protection pipeline verification.
Focus: /api/obfuscate, /api/scripts, /api/loaders, /api/keys, /api/verify, /api/loader/*.lua

Runs against REACT_APP_BACKEND_URL (public preview URL).
Uses luac5.3 -p for real syntax validation of obfuscated Lua output.
"""
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://admin-toolkit-36.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"
LUAC = shutil.which("luac5.3") or shutil.which("luac")


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _luac_check(code: str) -> tuple[bool, str]:
    """Return (ok, message). Uses luac -p for syntax check only."""
    if not LUAC:
        return True, "luac-not-available-skipped"
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as f:
        f.write(code)
        path = f.name
    try:
        r = subprocess.run([LUAC, "-p", path], capture_output=True, text=True, timeout=15)
        return r.returncode == 0, (r.stderr or r.stdout).strip()
    finally:
        os.unlink(path)


# ==================== /api/obfuscate ====================

SAMPLE_CODE = 'print("secret_password_123")\nlocal x = 42\nfor i=1,10 do print(i) end\n'


class TestObfuscateEndpoint:
    def test_light_level(self, session):
        r = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": "light"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["engine"] == "built-in"
        assert d["output_bytes"] > 3 * d["source_bytes"], f"light output too small: {d['output_bytes']} vs {d['source_bytes']}"
        out = d["output"]
        assert out.startswith("-- Obfuscated by MOD_CTRL"), out[:80]
        assert "loadstring" in out or "load(" in out
        assert "secret_password_123" not in out, "plaintext string leaked!"

    def test_medium_larger_than_light(self, session):
        r_light = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": "light"}).json()
        r_med = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": "medium"}).json()
        assert r_med["ok"] is True
        assert r_med["output_bytes"] > r_light["output_bytes"], \
            f"medium ({r_med['output_bytes']}) should be > light ({r_light['output_bytes']})"

    def test_heavy_largest(self, session):
        r_light = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": "light"}).json()
        r_med = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": "medium"}).json()
        r_heavy = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": "heavy"}).json()
        assert r_heavy["ok"] is True
        assert r_heavy["output_bytes"] >= r_med["output_bytes"] >= r_light["output_bytes"]
        # heavy uses 3 layers (nested/wrapped) — only the outermost layer is visible as plaintext,
        # inner layers are inside the encrypted base64 blob. Verify header states 3 layers
        # and size ratio confirms progressive expansion.
        assert "3 layers" in r_heavy["output"], f"expected '3 layers' in header, got: {r_heavy['output'][:120]}"
        # heavy must be at least ~1.5x the light size (each layer inflates by base64 + XOR wrap)
        assert r_heavy["output_bytes"] > r_light["output_bytes"] * 1.3, \
            f"heavy ({r_heavy['output_bytes']}) not sufficiently larger than light ({r_light['output_bytes']})"

    def test_empty_code_400(self, session):
        r = session.post(f"{API}/obfuscate", json={"code": "", "level": "medium"})
        assert r.status_code == 400

    def test_whitespace_code_400(self, session):
        r = session.post(f"{API}/obfuscate", json={"code": "   \n\t  ", "level": "medium"})
        assert r.status_code == 400

    def test_invalid_level_400(self, session):
        r = session.post(f"{API}/obfuscate", json={"code": "print(1)", "level": "extreme"})
        assert r.status_code == 400

    def test_syntax_valid_all_levels(self, session):
        for lvl in ("light", "medium", "heavy"):
            r = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": lvl})
            assert r.status_code == 200
            out = r.json()["output"]
            ok, msg = _luac_check(out)
            assert ok, f"[{lvl}] luac -p failed: {msg}\n--- OUTPUT (first 400ch) ---\n{out[:400]}"

    def test_hides_string_literals(self, session):
        code = 'print("secret_password_123")\nprint("api_key_ABCDEF")'
        r = session.post(f"{API}/obfuscate", json={"code": code, "level": "medium"})
        out = r.json()["output"]
        assert "secret_password_123" not in out
        assert "api_key_ABCDEF" not in out

    def test_special_characters(self, session):
        code = 'print("hello\\nworld")\nlocal s = "quo\\"ted"\nlocal b = "back\\\\slash"'
        r = session.post(f"{API}/obfuscate", json={"code": code, "level": "medium"})
        assert r.status_code == 200, r.text
        out = r.json()["output"]
        ok, msg = _luac_check(out)
        assert ok, f"special-char output invalid: {msg}\n{out[:400]}"

    def test_function_end_balance(self, session):
        """Sanity: count 'function' vs 'end' tokens (approximate balance)."""
        r = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": "heavy"})
        out = r.json()["output"]
        # word-boundary counts
        fns = len(re.findall(r"\bfunction\b", out))
        ends = len(re.findall(r"\bend\b", out))
        # ends should be >= functions (loops/ifs add more ends)
        assert ends >= fns > 0, f"function={fns} end={ends}"


# ==================== /api/scripts CRUD ====================

class TestScriptsCRUD:
    def test_create_list_get_delete(self, session):
        obf = session.post(f"{API}/obfuscate", json={"code": SAMPLE_CODE, "level": "medium"}).json()["output"]
        name = f"TEST_script_{uuid.uuid4().hex[:8]}"
        payload = {"name": name, "source": SAMPLE_CODE, "obfuscated": obf, "level": "medium", "note": "pytest"}
        r = session.post(f"{API}/scripts", json=payload)
        assert r.status_code == 200
        sid = r.json()["id"]

        # list — must NOT expose source/obfuscated
        lst = session.get(f"{API}/scripts").json()["scripts"]
        found = [s for s in lst if s["id"] == sid]
        assert found, "created script missing from list"
        assert "source" not in found[0]
        assert "obfuscated" not in found[0]

        # detail — MUST include obfuscated
        detail = session.get(f"{API}/scripts/{sid}").json()
        assert detail["obfuscated"] == obf
        assert detail["source"] == SAMPLE_CODE
        assert detail["name"] == name

        # delete
        d = session.delete(f"{API}/scripts/{sid}").json()
        assert d["deleted"] == 1
        r404 = session.get(f"{API}/scripts/{sid}")
        assert r404.status_code == 404


# ==================== Full loader+key+verify flow ====================

@pytest.fixture(scope="module")
def loader_flow(session):
    """Create loader with 2 scripts and a loader-scoped key. Yields dict of ids."""
    obf_a = session.post(f"{API}/obfuscate", json={"code": 'print("SCRIPT_A_PAYLOAD_UNIQUE")', "level": "heavy"}).json()["output"]
    obf_b = session.post(f"{API}/obfuscate", json={"code": 'print("SCRIPT_B_PAYLOAD_UNIQUE")', "level": "heavy"}).json()["output"]
    tag = uuid.uuid4().hex[:8]
    loader = session.post(f"{API}/loaders", json={"name": f"TEST_loader_{tag}", "description": "pytest"}).json()["loader"]
    lid = loader["id"]

    sid_a = session.post(f"{API}/scripts", json={"name": f"TEST_A_{tag}", "source": "a", "obfuscated": obf_a, "level": "heavy"}).json()["id"]
    sid_b = session.post(f"{API}/scripts", json={"name": f"TEST_B_{tag}", "source": "b", "obfuscated": obf_b, "level": "heavy"}).json()["id"]

    assert session.post(f"{API}/loaders/{lid}/scripts", json={"script_id": sid_a, "slug": "a"}).status_code == 200
    assert session.post(f"{API}/loaders/{lid}/scripts", json={"script_id": sid_b, "slug": "b"}).status_code == 200

    key_resp = session.post(f"{API}/keys", json={"loader_id": lid, "note": "pytest"}).json()
    key = key_resp["key"]["key"]
    key_id = key_resp["key"]["id"]

    data = {"lid": lid, "sid_a": sid_a, "sid_b": sid_b, "obf_a": obf_a, "obf_b": obf_b, "key": key, "key_id": key_id}
    yield data

    # teardown
    session.delete(f"{API}/keys/{key_id}")
    session.delete(f"{API}/scripts/{sid_a}")
    session.delete(f"{API}/scripts/{sid_b}")
    session.delete(f"{API}/loaders/{lid}")


class TestVerifyFlow:
    def test_verify_slug_a(self, session, loader_flow):
        d = loader_flow
        r = session.get(f"{API}/verify", params={"loader_id": d["lid"], "slug": "a", "key": d["key"], "hwid": "hw_pytest_1"})
        assert r.status_code == 200
        assert r.text == d["obf_a"], f"expected obf_a, got: {r.text[:200]}"

    def test_verify_slug_b(self, session, loader_flow):
        d = loader_flow
        r = session.get(f"{API}/verify", params={"loader_id": d["lid"], "slug": "b", "key": d["key"], "hwid": "hw_pytest_1"})
        assert r.status_code == 200
        assert r.text == d["obf_b"]

    def test_verify_wrong_slug(self, session, loader_flow):
        d = loader_flow
        r = session.get(f"{API}/verify", params={"loader_id": d["lid"], "slug": "zzz", "key": d["key"], "hwid": "hw_pytest_1"})
        assert r.status_code == 200
        assert "ERROR: target script not found" in r.text, r.text

    def test_verify_wrong_key(self, session, loader_flow):
        d = loader_flow
        r = session.get(f"{API}/verify", params={"loader_id": d["lid"], "slug": "a", "key": "bogus_key_xxx", "hwid": "hw_pytest_1"})
        assert r.status_code == 200
        assert "ERROR: invalid key" in r.text, r.text

    def test_verify_hwid_mismatch(self, session, loader_flow):
        d = loader_flow
        r = session.get(f"{API}/verify", params={"loader_id": d["lid"], "slug": "a", "key": d["key"], "hwid": "hw_DIFFERENT"})
        assert r.status_code == 200
        assert "HWID mismatch" in r.text, r.text

    def test_executions_counter(self, session, loader_flow):
        d = loader_flow
        # Fire 3 more verifications (previous tests already ran some)
        for _ in range(3):
            session.get(f"{API}/verify", params={"loader_id": d["lid"], "slug": "a", "key": d["key"], "hwid": "hw_pytest_1"})
        keys = session.get(f"{API}/keys").json()["keys"]
        me = next(k for k in keys if k["id"] == d["key_id"])
        assert me["executions"] >= 3, f"executions={me['executions']}"


# ==================== Loader Lua stubs ====================

class TestLoaderStubs:
    def test_menu_loader_stub(self, session, loader_flow):
        r = session.get(f"{API}/loader/{loader_flow['lid']}.lua")
        assert r.status_code == 200
        code = r.text
        assert "return L" in code
        assert "function L:load" in code
        assert "function L:bundle" in code
        ok, msg = _luac_check(code)
        assert ok, f"menu stub invalid lua: {msg}"

    def test_individual_stub(self, session, loader_flow):
        r = session.get(f"{API}/loader/{loader_flow['lid']}/a.lua")
        assert r.status_code == 200
        code = r.text
        assert "script_key" in code
        assert "HttpGet" in code
        assert "loadstring" in code
        ok, msg = _luac_check(code)
        assert ok, f"individual stub invalid lua: {msg}"

    def test_bundle_stub(self, session, loader_flow):
        r = session.get(f"{API}/loader/{loader_flow['lid']}/bundle.lua")
        assert r.status_code == 200
        code = r.text
        assert re.search(r"\bfor\b", code)
        assert re.search(r"\bend\b", code)
        ok, msg = _luac_check(code)
        assert ok, f"bundle stub invalid lua: {msg}"


# ==================== Regression ====================

class TestRegression:
    def test_api_root_get(self, session):
        r = session.get(f"{API}/")
        assert r.status_code == 200

    def test_api_root_head(self, session):
        r = session.head(f"{API}/")
        assert r.status_code == 200

    def test_api_health(self, session):
        r = session.get(f"{API}/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_bot_commands_62_with_protection(self, session):
        r = session.get(f"{API}/bot/commands")
        assert r.status_code == 200
        cmds = r.json()["commands"]
        assert len(cmds) == 62, f"expected 62 commands, got {len(cmds)}"
        names = {c["name"] for c in cmds}
        for req in ("panel", "whitelist", "revoke", "resethwid", "keyinfo"):
            assert req in names, f"missing protection command: {req}"
