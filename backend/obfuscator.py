"""
Lua Obfuscator — MOD_CTRL

Engines (in priority order):
  1. Prometheus (open-source, bundled)  → best quality, VM-based, control-flow flattening.
     Requires `lua5.3` on the host. Uses presets: Minify / Weak / Medium / Strong.
  2. luaobfuscator.com API               → if a user API key is configured.
  3. Built-in XOR/Base64 multi-layer     → last-resort fallback.

Levels → engine map:
  light   → Prometheus "Weak"     (fast, small blow-up)
  medium  → Prometheus "Medium"   (VM, string encryption)
  heavy   → Prometheus "Strong"   (full control-flow flattening, VM, junk code)
"""
from __future__ import annotations
import asyncio
import base64
import os
import re
import secrets
import string
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

import httpx

# ---------- Prometheus config ----------
PROMETHEUS_DIR = Path(__file__).parent / "prometheus"
PROMETHEUS_CLI = PROMETHEUS_DIR / "cli.lua"
LUA_BIN = os.environ.get("LUA_BIN", "lua5.3")

# Map our level names to Prometheus preset names.
PROMETHEUS_PRESET = {
    "light": "Weak",
    "medium": "Medium",
    "heavy": "Strong",
}


def _prometheus_available() -> bool:
    """Check that lua5.3 + Prometheus source are both on-disk."""
    if not PROMETHEUS_CLI.exists():
        return False
    try:
        subprocess.run([LUA_BIN, "-v"], capture_output=True, timeout=3, check=False)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


async def obfuscate_via_prometheus(code: str, level: str) -> str:
    """Shell out to Prometheus CLI. Runs in a thread so it doesn't block the loop."""
    preset = PROMETHEUS_PRESET.get(level, "Medium")

    def _run() -> str:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.lua"
            out = Path(td) / "out.lua"
            src.write_text(code, encoding="utf-8")
            r = subprocess.run(
                [LUA_BIN, str(PROMETHEUS_CLI),
                 "--preset", preset,
                 "--nocolors",
                 "--out", str(out),
                 str(src)],
                cwd=str(PROMETHEUS_DIR),
                capture_output=True,
                timeout=90,
            )
            if r.returncode != 0 or not out.exists():
                raise RuntimeError(
                    f"prometheus failed (rc={r.returncode}): "
                    f"{(r.stderr or r.stdout).decode(errors='replace')[:800]}"
                )
            return out.read_text(encoding="utf-8", errors="replace")

    return await asyncio.to_thread(_run)


# ---------- luaobfuscator.com (secondary) ----------
LUAOBFUSCATOR_BASE = "https://api.luaobfuscator.com/v1"

PRESETS = {
    "light": {
        "MinifiyAll": True,
        "CustomPlugins": {
            "EncryptStrings": [80],
            "Minifier": [True],
        },
    },
    "medium": {
        "MinifiyAll": True,
        "CustomPlugins": {
            "EncryptStrings": [100],
            "MutateAllLiterals": [100],
            "SwizzleLookups": [60],
            "Minifier": [True],
        },
    },
    "heavy": {
        "MinifiyAll": True,
        "Virtualize": True,
        "CustomPlugins": {
            "EncryptStrings": [100],
            "MutateAllLiterals": [100],
            "ControlFlowFlattenV1AllBlocks": [70],
            "SwizzleLookups": [80],
            "JunkifyAllIfStatements": [50],
            "JunkifyBlockToIf": [50],
            "CallRetAssignment": [40],
            "Minifier": [True],
        },
    },
}


class LuaObfuscatorAPIError(Exception):
    pass


async def obfuscate_via_api(code: str, level: str, api_key: str) -> str:
    if level not in PRESETS:
        raise LuaObfuscatorAPIError(f"Invalid level: {level}")
    async with httpx.AsyncClient(timeout=60) as h:
        r = await h.post(
            f"{LUAOBFUSCATOR_BASE}/obfuscator/newscript",
            headers={"apikey": api_key, "content-type": "text/plain"},
            content=code.encode("utf-8"),
        )
        if r.status_code >= 400:
            raise LuaObfuscatorAPIError(f"newscript failed: {r.status_code} {r.text}")
        data = r.json()
        session_id = data.get("sessionId")
        if not session_id:
            raise LuaObfuscatorAPIError(
                f"newscript returned no session: {data.get('message') or data}"
            )
        r2 = await h.post(
            f"{LUAOBFUSCATOR_BASE}/obfuscator/obfuscate",
            headers={
                "apikey": api_key,
                "sessionId": session_id,
                "content-type": "application/json",
            },
            json=PRESETS[level],
        )
        if r2.status_code >= 400:
            raise LuaObfuscatorAPIError(f"obfuscate failed: {r2.status_code} {r2.text}")
        out = r2.json()
        if out.get("message"):
            raise LuaObfuscatorAPIError(str(out["message"]))
        return out.get("code") or ""


# ---------- Built-in fallback (last resort) ----------
_STRING_RE = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', re.DOTALL)
_COMMENT_LINE_RE = re.compile(r"--[^\n\r]*")
_COMMENT_BLOCK_RE = re.compile(r"--\[\[.*?\]\]", re.DOTALL)
_NUM_RE = re.compile(r"(?<![A-Za-z_0-9\.])(\d+)(?![A-Za-z_0-9\.])")


def _rand(n: int = 8) -> str:
    return "_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _strip(code: str) -> str:
    code = _COMMENT_BLOCK_RE.sub("", code)
    code = _COMMENT_LINE_RE.sub("", code)
    return re.sub(r"[ \t]+", " ", code).strip()


DECODER = """
local function {dec}(s)
    local k = "{key}"
    local b = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    s = string.gsub(s, '[^'..b..'=]', ''); local n=0; local buf=0; local d=""
    for i=1,#s do
        local c = string.find(b, string.sub(s,i,i), 1, true)
        if c then buf=buf*64+(c-1); n=n+6
            if n>=8 then n=n-8; d=d..string.char(math.floor(buf/(2^n))%256); buf=buf%(2^n) end
        end
    end
    local out={{}}
    for i=1,#d do
        local a,b2=string.byte(d,i),string.byte(k,((i-1)%#k)+1)
        out[i]=string.char(bit32 and bit32.bxor(a,b2) or ((a+b2)%256))
    end
    return table.concat(out)
end
""".strip()


def obfuscate_fallback(code: str, level: str = "medium") -> str:
    code = _strip(code)
    key = secrets.token_hex(6)
    dec = _rand(10)
    kb = key.encode()

    def repl(m):
        raw = m.group(0)[1:-1]
        cipher = _xor_bytes(raw.encode("utf-8", "ignore"), kb)
        return f'{dec}("{base64.b64encode(cipher).decode()}")'
    code = _STRING_RE.sub(repl, code)
    code = DECODER.format(dec=dec, key=key) + "\n" + code

    if level in ("medium", "heavy"):
        def numrepl(m):
            n = int(m.group(1))
            if n == 0: return "(1-1)"
            a = secrets.randbelow(max(1, n)) + 1
            return f"({a}+{n-a})"
        code = _NUM_RE.sub(numrepl, code)

    layers = 1 if level == "light" else (2 if level == "medium" else 3)
    for _ in range(layers):
        k2 = secrets.token_hex(8)
        dec2 = _rand(10)
        ld = _rand(10)
        cipher = _xor_bytes(code.encode("utf-8"), k2.encode())
        b64 = base64.b64encode(cipher).decode()
        decoder = DECODER.format(dec=dec2, key=k2)
        code = (
            f"local function {ld}()\n"
            f"    local {dec2}=(function() {decoder} return {dec2} end)()\n"
            f'    local src={dec2}("{b64}")\n'
            "    local fn,err=loadstring and loadstring(src) or load(src)\n"
            "    if not fn then error(err) end\n"
            "    return fn()\n"
            f"end\n{ld}()"
        )
    return f"-- Obfuscated by MOD_CTRL (built-in, {layers} layers)\n" + code


# ---------- Public entrypoint ----------
async def obfuscate(code: str, level: str = "medium",
                    api_key: Optional[str] = None,
                    engine: Optional[str] = None) -> Tuple[str, str]:
    """Try Prometheus → luaobfuscator.com API → built-in.

    `engine` can be "prometheus", "luaobfuscator", "builtin", or None (auto).
    Returns (obfuscated_output, engine_used_label).
    """
    if level not in ("light", "medium", "heavy"):
        level = "medium"

    # 1) Prometheus (default when available)
    if engine in (None, "prometheus", "auto") and _prometheus_available():
        try:
            out = await obfuscate_via_prometheus(code, level)
            return out, f"prometheus ({PROMETHEUS_PRESET[level]})"
        except Exception as e:
            if engine == "prometheus":
                # user forced it — surface the error via fallback message
                pass
            # fall through
            fallback_reason = f"prometheus error: {e}"
        else:
            fallback_reason = ""
    else:
        fallback_reason = "prometheus unavailable"

    # 2) luaobfuscator.com API (if key provided)
    if api_key and engine in (None, "luaobfuscator", "auto"):
        try:
            out = await obfuscate_via_api(code, level, api_key)
            return out, "luaobfuscator.com"
        except Exception as e:
            fallback_reason = f"{fallback_reason}; api error: {e}" if fallback_reason else f"api error: {e}"

    # 3) Built-in fallback
    return obfuscate_fallback(code, level), f"built-in ({fallback_reason})" if fallback_reason else "built-in"
