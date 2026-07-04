import { useEffect, useState } from "react";
import { api } from "@/lib/botApi";
import { toast } from "sonner";
import { Copy, RefreshCcw, Trash2, Plus, Loader2, KeySquare } from "lucide-react";

export default function KeysPage() {
  const [keys, setKeys] = useState([]);
  const [scripts, setScripts] = useState([]);
  const [loaders, setLoaders] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ target: "", discord_id: "", note: "", expires_days: 0, max_executions: 0, bulk_count: 10 });
  const [backendUrl] = useState(process.env.REACT_APP_BACKEND_URL);

  const load = async () => {
    setLoading(true);
    try {
      const [k, s, l] = await Promise.all([
        api.get("/keys"),
        api.get("/scripts"),
        api.get("/loaders"),
      ]);
      setKeys(k.data.keys || []);
      setScripts(s.data.scripts || []);
      setLoaders(l.data.loaders || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!form.target) {
      toast.error("Pick a script or loader");
      return;
    }
    const [kind, id] = form.target.split(":", 2);
    setCreating(true);
    try {
      const body = {
        discord_id: form.discord_id || null,
        note: form.note || null,
        expires_days: form.expires_days ? Number(form.expires_days) : null,
        max_executions: form.max_executions ? Number(form.max_executions) : null,
      };
      if (kind === "loader") body.loader_id = id; else body.script_id = id;
      const r = await api.post("/keys", body);
      toast.success("Key created");
      await navigator.clipboard.writeText(r.data.key.key);
      toast.success("Key copied to clipboard");
      setForm({ ...form, discord_id: "", note: "" });
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to create key");
    } finally {
      setCreating(false);
    }
  };

  const bulkCreate = async () => {
    if (!form.target) { toast.error("Pick a script or loader"); return; }
    const count = Number(form.bulk_count) || 10;
    if (count < 1 || count > 500) { toast.error("count must be 1-500"); return; }
    const [kind, id] = form.target.split(":", 2);
    setCreating(true);
    try {
      const body = {
        count,
        expires_days: form.expires_days ? Number(form.expires_days) : null,
        max_executions: form.max_executions ? Number(form.max_executions) : null,
        note: form.note || "bulk",
      };
      if (kind === "loader") body.loader_id = id; else body.script_id = id;
      const r = await api.post("/keys/bulk", body);
      const list = (r.data.keys || []).join("\n");
      const blob = new Blob([list], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `keys-${count}-${Date.now()}.txt`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Generated ${r.data.count} keys — downloaded as .txt`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Bulk create failed");
    } finally {
      setCreating(false);
    }
  };

  const revoke = async (id) => {
    if (!window.confirm("Revoke this key?")) return;
    await api.delete(`/keys/${id}`);
    toast.success("Revoked");
    await load();
  };

  const resetHwid = async (id) => {
    await api.post(`/keys/${id}/resethwid`);
    toast.success("HWID reset — cooldown cleared, key unlocked");
    await load();
  };

  const copyKey = async (k) => {
    await navigator.clipboard.writeText(k);
    toast.success("Key copied");
  };

  const copyLoader = async (k) => {
    const id = k.loader_id || k.script_id;
    const suffix = k.loader_id ? `${id}/bundle.lua` : `${id}.lua`;
    const url = `${backendUrl}/api/loader/${suffix}`;
    const snippet = `script_key = "${k.key}"\nloadstring(game:HttpGet("${url}"))()`;
    await navigator.clipboard.writeText(snippet);
    toast.success("Loader snippet copied");
  };

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div>
        <div className="text-[10px] tracking-[0.25em] text-white/40 uppercase font-bold">
          SECTOR 07
        </div>
        <h1
          className="text-3xl sm:text-4xl font-black tracking-tighter uppercase text-white mt-1"
          style={{ fontFamily: "Chivo, sans-serif" }}
          data-testid="keys-title"
        >
          Whitelist Keys
        </h1>
        <p className="text-white/50 text-sm mt-1 max-w-2xl">
          Self-hosted key check. Generate keys tied to a script, lock to HWID on first use, and
          revoke any time. Users load your script via a loader that validates the key with your
          backend before returning the obfuscated payload.
        </p>
      </div>

      {/* Create */}
      <div className="border border-white/10 bg-[#0A0A0A] p-4 space-y-3">
        <div className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold">
          GENERATE NEW KEY
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <select
            data-testid="key-target"
            value={form.target}
            onChange={(e) => setForm({ ...form, target: e.target.value })}
            className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white"
          >
            <option value="">— pick a script or loader —</option>
            {loaders.length > 0 && (
              <optgroup label="Loaders (bundle of scripts)">
                {loaders.map((l) => (
                  <option key={l.id} value={`loader:${l.id}`}>
                    📦 {l.name} — {(l.scripts || []).length} script(s)
                  </option>
                ))}
              </optgroup>
            )}
            {scripts.length > 0 && (
              <optgroup label="Standalone Scripts">
                {scripts.map((s) => (
                  <option key={s.id} value={`script:${s.id}`}>
                    📄 {s.name} ({s.level})
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <input
            data-testid="key-discord"
            value={form.discord_id}
            onChange={(e) => setForm({ ...form, discord_id: e.target.value })}
            placeholder="discord id (optional)"
            className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
          />
          <input
            data-testid="key-note"
            value={form.note}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
            placeholder="note (optional)"
            className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
          />
          <input
            data-testid="key-expires"
            type="number"
            min="0"
            value={form.expires_days}
            onChange={(e) => setForm({ ...form, expires_days: e.target.value })}
            placeholder="expires in N days (0 = never)"
            className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
          />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          <input
            data-testid="key-max-exec"
            type="number"
            min="0"
            value={form.max_executions}
            onChange={(e) => setForm({ ...form, max_executions: e.target.value })}
            placeholder="max executions (0 = unlimited)"
            className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
          />
          <input
            data-testid="key-bulk-count"
            type="number"
            min="1"
            max="500"
            value={form.bulk_count}
            onChange={(e) => setForm({ ...form, bulk_count: e.target.value })}
            placeholder="bulk generate: how many keys (1-500)"
            className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
          />
        </div>
        <div className="flex flex-wrap gap-2">
        <button
          data-testid="key-create"
          onClick={create}
          disabled={creating}
          className="inline-flex items-center gap-2 border border-[#34C759] bg-[#34C759]/10 hover:bg-[#34C759]/20 text-[#34C759] px-4 py-2 text-xs uppercase tracking-[0.2em] font-bold transition-colors duration-75 disabled:opacity-50"
        >
          {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
          Generate Key
        </button>
        <button
          data-testid="key-bulk-create"
          onClick={bulkCreate}
          disabled={creating}
          className="inline-flex items-center gap-2 border border-[#3395FF] bg-[#3395FF]/10 hover:bg-[#3395FF]/20 text-[#3395FF] px-4 py-2 text-xs uppercase tracking-[0.2em] font-bold transition-colors duration-75 disabled:opacity-50"
        >
          <Plus className="w-3.5 h-3.5" />
          Bulk Generate ({form.bulk_count || 10})
        </button>
        </div>
      </div>

      {/* Table */}
      <div className="border border-white/10 bg-[#0A0A0A] overflow-x-auto">
        <div className="grid grid-cols-[1fr_140px_100px_80px_100px_140px] px-3 py-2 border-b border-white/10 text-[10px] uppercase tracking-[0.25em] text-white/40 font-bold min-w-[900px]">
          <span>Key · Script</span>
          <span>Discord</span>
          <span>HWID</span>
          <span className="text-right">Runs</span>
          <span>Expires</span>
          <span className="text-right">Actions</span>
        </div>
        {keys.length === 0 ? (
          <div className="px-3 py-10 text-center text-white/30 text-sm font-mono">
            {loading ? "loading…" : "no keys yet — generate one above"}
          </div>
        ) : (
          keys.map((k) => (
            <div
              key={k.id}
              data-testid={`key-row-${k.id}`}
              className="grid grid-cols-[1fr_140px_100px_80px_100px_140px] px-3 py-2.5 border-b border-white/5 text-xs items-center hover:bg-white/[0.03] min-w-[900px]"
            >
              <div className="min-w-0">
                <div className="font-mono text-[11px] text-white truncate flex items-center gap-2">
                  <KeySquare className="w-3.5 h-3.5 text-white/40 shrink-0" />
                  <span className="truncate">{k.key}</span>
                </div>
                <div className="text-[10px] text-white/40 mt-0.5 font-mono truncate">
                  {k.loader_id
                    ? `📦 ${k.loader_name || k.loader_id}`
                    : `📄 ${k.script_name || k.script_id}`}
                  {" · "}
                  {k.status === "locked" ? (
                    <span className="text-[#FF6961]">LOCKED</span>
                  ) : (
                    k.note || "no note"
                  )}
                </div>
              </div>
              <span className="font-mono text-white/60 truncate">{k.discord_id || "—"}</span>
              <span className={`font-mono text-[10px] ${k.hwid ? "text-[#34C759]" : "text-white/30"}`}>
                {k.hwid ? "locked" : "unbound"}
              </span>
              <span className="font-mono text-white/70 text-right">{k.executions ?? 0}</span>
              <span className="font-mono text-[10px] text-white/50">
                {k.expires_at ? new Date(k.expires_at).toLocaleDateString() : "never"}
              </span>
              <div className="flex items-center gap-1 justify-end">
                <button onClick={() => copyKey(k.key)} title="Copy key"
                  className="p-1.5 border border-white/10 hover:border-white/30 text-white/60 hover:text-white transition-colors duration-75">
                  <Copy className="w-3.5 h-3.5" />
                </button>
                <button onClick={() => copyLoader(k)} title="Copy loader snippet"
                  className="p-1.5 border border-white/10 hover:border-white/30 text-white/60 hover:text-white transition-colors duration-75 text-[10px] font-mono">
                  ldr
                </button>
                <button onClick={() => resetHwid(k.id)} title="Reset HWID"
                  className="p-1.5 border border-white/10 hover:border-[#FFCC00]/40 hover:text-[#FFCC00] text-white/60 transition-colors duration-75">
                  <RefreshCcw className="w-3.5 h-3.5" />
                </button>
                <button onClick={() => revoke(k.id)} title="Revoke"
                  className="p-1.5 border border-white/10 hover:border-[#FF3B30]/50 hover:text-[#FF6961] text-white/60 transition-colors duration-75">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      {/* How it works */}
      <div className="border border-white/10 bg-[#0A0A0A] p-4">
        <div className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold mb-2">
          HOW USERS EXECUTE YOUR SCRIPT
        </div>
        <ol className="text-xs text-white/70 space-y-1.5 leading-relaxed">
          <li>1. You obfuscate + save the script in the <span className="text-white">Obfuscator</span> tab.</li>
          <li>2. You generate a key above and share it with your customer (or click the <span className="font-mono">ldr</span> button for a ready-to-paste snippet).</li>
          <li>3. Customer pastes this into their executor:
            <pre className="mt-1 bg-black border border-white/10 p-2 font-mono text-[10px] overflow-x-auto text-[#3395FF]">
{`script_key = "THEIR_KEY"
loadstring(game:HttpGet("${backendUrl}/api/loader/<script_id>.lua"))()`}
            </pre>
          </li>
          <li>4. Your loader hits <span className="font-mono">/api/verify</span>, checks key + HWID, returns obfuscated payload only if valid.</li>
          <li>5. Every execution bumps the counter. You can revoke, reset HWID, or expire the key any time.</li>
        </ol>
      </div>
    </div>
  );
}
