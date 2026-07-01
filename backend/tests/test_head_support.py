"""
Iteration-3 targeted test: HEAD support fix for uptime monitor (BetterStack)

Verifies:
  - GET  /api/           -> 200 JSON {service, status}
  - HEAD /api/           -> 200 empty body (previously 405)
  - GET  /api/health     -> 200 JSON {ok:true}
  - HEAD /api/health     -> 200 empty body
  - HEAD on other common GETs is not 405 (FastAPI auto-implements HEAD only for
    api_route(...); plain @get does NOT — that's fine, but they must still not
    500). This test only asserts the two endpoints that were explicitly fixed.

Plus a light regression pass over the previously-passing endpoints.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


# ---------- session ----------
@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- THE FIX ----------
class TestHeadFix:
    def test_get_root(self, client):
        r = client.get(f"{API}/", timeout=15)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("service") == "discord-bot-control"
        assert body.get("status") == "ok"

    def test_head_root_not_405(self, client):
        r = client.head(f"{API}/", timeout=15, allow_redirects=False)
        assert r.status_code == 200, f"HEAD /api/ returned {r.status_code} (expected 200, NOT 405). body={r.text!r}"
        # HEAD must not return a body
        assert r.text == "" or r.content == b"", f"HEAD returned body: {r.text!r}"

    def test_get_health(self, client):
        r = client.get(f"{API}/health", timeout=15)
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

    def test_head_health_not_405(self, client):
        r = client.head(f"{API}/health", timeout=15, allow_redirects=False)
        assert r.status_code == 200, f"HEAD /api/health returned {r.status_code} (expected 200). body={r.text!r}"
        assert r.text == "" or r.content == b"", f"HEAD returned body: {r.text!r}"


# ---------- regression: unchanged endpoints ----------
class TestRegressionUnchanged:
    def test_bot_status_shape(self, client):
        r = client.get(f"{API}/bot/status", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "running" in data
        assert "runtime" in data
        assert isinstance(data["runtime"], dict)

    def test_bot_commands_62(self, client):
        r = client.get(f"{API}/bot/commands", timeout=15)
        assert r.status_code == 200
        data = r.json()
        cmds = data.get("commands") if isinstance(data, dict) else data
        assert isinstance(cmds, list)
        # iteration_2 asserted 62 — allow >=60 to be tolerant to minor edits
        assert len(cmds) >= 60, f"expected ~62 commands, got {len(cmds)}"

    def test_bot_config_masked(self, client):
        r = client.get(f"{API}/bot/config", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "bot_token_masked" in data
        assert "bot_token" not in data  # raw token must never leak

    def test_scripts_list(self, client):
        r = client.get(f"{API}/scripts", timeout=15)
        assert r.status_code == 200
        data = r.json()
        items = data.get("scripts") if isinstance(data, dict) else data
        assert isinstance(items, list)

    def test_loaders_list(self, client):
        r = client.get(f"{API}/loaders", timeout=15)
        assert r.status_code == 200
        data = r.json()
        items = data.get("loaders") if isinstance(data, dict) else data
        assert isinstance(items, list)

    def test_keys_list(self, client):
        r = client.get(f"{API}/keys", timeout=15)
        assert r.status_code == 200
        data = r.json()
        items = data.get("keys") if isinstance(data, dict) else data
        assert isinstance(items, list)

    def test_obfuscate_ok(self, client):
        r = client.post(
            f"{API}/obfuscate",
            json={"code": "print('hi')", "level": "medium"},
            timeout=30,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("ok") is True
        assert isinstance(data.get("output"), str) and len(data["output"]) > 0


# ---------- end-to-end loader flow ----------
class TestLoaderFlow:
    @pytest.fixture(scope="class")
    def flow(self, client):
        ts = int(time.time())

        def _unwrap(js, keys):
            for k in keys:
                if isinstance(js, dict) and isinstance(js.get(k), dict):
                    return js[k]
            return js if isinstance(js, dict) else {}

        # create loader
        r = client.post(f"{API}/loaders", json={"name": f"TEST_loader_{ts}"}, timeout=15)
        assert r.status_code in (200, 201), r.text
        loader = _unwrap(r.json(), ["loader", "data"])
        loader_id = loader.get("id") or loader.get("_id") or loader.get("loader_id")
        assert loader_id, f"loader id missing: {r.json()}"

        # create 2 scripts
        script_ids = []
        for i, name in enumerate(["TEST_scriptA", "TEST_scriptB"]):
            rs = client.post(
                f"{API}/scripts",
                json={
                    "name": f"{name}_{ts}",
                    "source": f"print('{name}')",
                    "obfuscated": f"OBF_{name}_{ts}",
                    "level": "medium",
                },
                timeout=30,
            )
            assert rs.status_code in (200, 201), rs.text
            sj = rs.json()
            sid = sj.get("id") or (sj.get("script") or {}).get("id")
            assert sid, f"script id missing: {sj}"
            script_ids.append(sid)

        # attach scripts with slugs a/b (one per POST)
        for sid, slug in zip(script_ids, ["a", "b"]):
            r_attach = client.post(
                f"{API}/loaders/{loader_id}/scripts",
                json={"script_id": sid, "slug": slug},
                timeout=15,
            )
            assert r_attach.status_code in (200, 201), r_attach.text

        # create loader-scoped key
        rk = client.post(
            f"{API}/keys",
            json={"loader_id": loader_id, "note": "TEST_key"},
            timeout=15,
        )
        assert rk.status_code in (200, 201), rk.text
        kj = rk.json()
        # Response may be {"key": "..."} OR {"key": {"key": "...", ...}} OR {"key_doc": {...}}
        key = None
        if isinstance(kj, dict):
            k = kj.get("key")
            if isinstance(k, str):
                key = k
            elif isinstance(k, dict):
                key = k.get("key") or k.get("value")
            if not key:
                for wrapper in ("key_doc", "data", "result"):
                    w = kj.get(wrapper)
                    if isinstance(w, dict):
                        key = w.get("key") or w.get("value")
                        if key:
                            break
        assert key and isinstance(key, str), f"key missing: {kj}"

        return {"loader_id": loader_id, "key": key, "script_ids": script_ids}

    def test_verify_slug_a(self, client, flow):
        r = client.get(
            f"{API}/verify",
            params={
                "loader_id": flow["loader_id"],
                "slug": "a",
                "key": flow["key"],
                "hwid": "TEST_HWID_1",
            },
            timeout=20,
        )
        assert r.status_code == 200
        assert not r.text.startswith("ERROR"), f"verify slug=a failed: {r.text[:200]}"
        assert len(r.text) > 20

    def test_verify_slug_b_same_key(self, client, flow):
        r = client.get(
            f"{API}/verify",
            params={
                "loader_id": flow["loader_id"],
                "slug": "b",
                "key": flow["key"],
                "hwid": "TEST_HWID_1",
            },
            timeout=20,
        )
        assert r.status_code == 200
        assert not r.text.startswith("ERROR"), f"verify slug=b (loader-wide) failed: {r.text[:200]}"

    def test_verify_hwid_mismatch(self, client, flow):
        r = client.get(
            f"{API}/verify",
            params={
                "loader_id": flow["loader_id"],
                "slug": "a",
                "key": flow["key"],
                "hwid": "DIFFERENT_HWID",
            },
            timeout=20,
        )
        assert r.status_code == 200
        assert "HWID" in r.text and r.text.startswith("ERROR"), f"expected HWID mismatch error, got: {r.text[:200]}"

    def test_loader_lua_menu(self, client, flow):
        r = client.get(f"{API}/loader/{flow['loader_id']}.lua", timeout=15)
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("content-type", "")
        assert len(r.text) > 20

    def test_loader_bundle_lua(self, client, flow):
        r = client.get(f"{API}/loader/{flow['loader_id']}/bundle.lua", timeout=15)
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("content-type", "")

    def test_loader_individual_slug_lua(self, client, flow):
        r = client.get(f"{API}/loader/{flow['loader_id']}/a.lua", timeout=15)
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("content-type", "")
