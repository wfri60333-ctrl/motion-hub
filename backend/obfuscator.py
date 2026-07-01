"""
Lua Obfuscator — MOD_CTRL
Uses the luaobfuscator.com HTTP API (real, professional-grade obfuscation with control
flow flattening, string encryption, VM virtualization, etc).

Falls back to the built-in multi-layer XOR/base64 obfuscator when no API key is set.
Get a free API key at: https://luaobfuscator.com/forum/keys
"""
from __future__ import annotations
import base64
import re
import secrets
import string
from typing import Optional

import httpx

LUAOBFUSCATOR_BASE = "https://api.luaobfuscator.com/v1"

# Preset plugin configs for each level
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
    """Two-step call: create session → apply obfuscation."""
    if level not in PRESETS:
        raise LuaObfuscatorAPIError(f"Invalid level: {level}")

    async with httpx.AsyncClient(timeout=60) as h:
        # 1. new session
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

        # 2. obfuscate
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


# ==================================================================
# Fallback built-in obfuscator (used when no API key is configured)
# ==================================================================

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

    # Encrypt string literals
    kb = key.encode()
    def repl(m):
        raw = m.group(0)[1:-1]
        cipher = _xor_bytes(raw.encode("utf-8", "ignore"), kb)
        return f'{dec}("{base64.b64encode(cipher).decode()}")'
    code = _STRING_RE.sub(repl, code)
    code = DECODER.format(dec=dec, key=key) + "\n" + code

    # Number obfuscation
    if level in ("medium", "heavy"):
        def numrepl(m):
            n = int(m.group(1))
            if n == 0: return "(1-1)"
            a = secrets.randbelow(max(1, n)) + 1
            return f"({a}+{n-a})"
        code = _NUM_RE.sub(numrepl, code)

    # Wrap layers
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


async def obfuscate(code: str, level: str = "medium",
                    api_key: Optional[str] = None) -> tuple[str, str]:
    """Try API first if key provided, else fallback. Returns (output, engine_used)."""
    if api_key:
        try:
            out = await obfuscate_via_api(code, level, api_key)
            return out, "luaobfuscator.com"
        except Exception as e:
            # Fall through to built-in
            fallback = obfuscate_fallback(code, level)
            return fallback, f"fallback (API error: {e})"
    return obfuscate_fallback(code, level), "built-in"
