import { useState } from "react";
import { api } from "@/lib/botApi";
import { toast } from "sonner";
import { Sparkles, Copy, Download, Save, Loader2, Zap, Shield, Flame } from "lucide-react";

const SAMPLE = `-- paste your Lua script here
print("hello world")
local function greet(name)
    return "hi " .. name
end
print(greet("nxtro"))`;

const LEVELS = [
  { id: "light", label: "Light", icon: Zap, tag: "1 layer · strings", tone: "text-white" },
  { id: "medium", label: "Medium", icon: Shield, tag: "2 layers · strings + numbers", tone: "text-[#3395FF]" },
  { id: "heavy", label: "Heavy", icon: Flame, tag: "3 layers · anti-hook + junk", tone: "text-[#FF6961]" },
];

export default function ObfuscatorPage() {
  const [source, setSource] = useState(SAMPLE);
  const [level, setLevel] = useState("heavy");
  const [output, setOutput] = useState("");
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState(null);
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const run = async () => {
    if (!source.trim()) {
      toast.error("Paste some Lua code first");
      return;
    }
    setBusy(true);
    try {
      const r = await api.post("/obfuscate", { code: source, level });
      setOutput(r.data.output);
      setStats({
        sourceBytes: r.data.source_bytes,
        outputBytes: r.data.output_bytes,
        ratio: (r.data.output_bytes / Math.max(1, r.data.source_bytes)).toFixed(2),
      });
      toast.success(`Obfuscated · ${r.data.output_bytes} bytes`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Obfuscation failed");
    } finally {
      setBusy(false);
    }
  };

  const copyOut = async () => {
    if (!output) return;
    await navigator.clipboard.writeText(output);
    toast.success("Copied to clipboard");
  };

  const downloadOut = () => {
    if (!output) return;
    const blob = new Blob([output], { type: "text/x-lua" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name || "script"}_${level}.lua`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const save = async () => {
    if (!output) {
      toast.error("Nothing to save — obfuscate first");
      return;
    }
    if (!name.trim()) {
      toast.error("Give it a name");
      return;
    }
    setSaving(true);
    try {
      await api.post("/scripts", {
        name: name.trim(),
        source,
        obfuscated: output,
        level,
      });
      toast.success("Saved to library");
      setName("");
    } catch (e) {
      toast.error("Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] tracking-[0.25em] text-white/40 uppercase font-bold">
            SECTOR 05
          </div>
          <h1
            className="text-3xl sm:text-4xl font-black tracking-tighter uppercase text-white mt-1"
            style={{ fontFamily: "Chivo, sans-serif" }}
            data-testid="obf-title"
          >
            Lua Obfuscator
          </h1>
          <p className="text-white/50 text-sm mt-1 max-w-2xl">
            Multi-layer XOR + Base64 wrapping, encrypted string literals, arithmetic-obfuscated numbers,
            junk code, and anti-hook checks. Nothing is unbreakable — but this stops casual reversers cold.
          </p>
        </div>
      </div>

      {/* Level selector */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {LEVELS.map((l) => (
          <button
            key={l.id}
            data-testid={`level-${l.id}`}
            onClick={() => setLevel(l.id)}
            className={`text-left border p-4 transition-colors duration-75 ${
              level === l.id
                ? "border-[#007AFF] bg-[#007AFF]/[0.08]"
                : "border-white/10 bg-[#0A0A0A] hover:border-white/30"
            }`}
          >
            <div className="flex items-center gap-2">
              <l.icon className={`w-4 h-4 ${l.tone}`} />
              <span className="text-sm uppercase tracking-[0.2em] font-bold text-white">
                {l.label}
              </span>
            </div>
            <div className="text-xs text-white/50 mt-2 font-mono">{l.tag}</div>
          </button>
        ))}
      </div>

      {/* Editor grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Input */}
        <div className="border border-white/10 bg-[#0A0A0A] flex flex-col h-[500px]">
          <div className="px-3 py-2 border-b border-white/10 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold">
              SOURCE
            </span>
            <span className="font-mono text-[10px] text-white/40">
              {source.length} bytes
            </span>
          </div>
          <textarea
            data-testid="obf-source"
            value={source}
            onChange={(e) => setSource(e.target.value)}
            spellCheck={false}
            className="flex-1 bg-black text-[#e8ffe8] font-mono text-xs leading-relaxed p-3 outline-none resize-none tactical-scroll"
          />
        </div>

        {/* Output */}
        <div className="border border-white/10 bg-[#0A0A0A] flex flex-col h-[500px]">
          <div className="px-3 py-2 border-b border-white/10 flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold">
              OBFUSCATED
            </span>
            <div className="flex items-center gap-2">
              {stats && (
                <span className="font-mono text-[10px] text-white/40">
                  {stats.outputBytes} bytes · x{stats.ratio}
                </span>
              )}
              <button
                data-testid="obf-copy"
                onClick={copyOut}
                disabled={!output}
                className="p-1.5 border border-white/10 hover:border-white/30 text-white/60 hover:text-white disabled:opacity-30 transition-colors duration-75"
                title="Copy"
              >
                <Copy className="w-3.5 h-3.5" />
              </button>
              <button
                data-testid="obf-download"
                onClick={downloadOut}
                disabled={!output}
                className="p-1.5 border border-white/10 hover:border-white/30 text-white/60 hover:text-white disabled:opacity-30 transition-colors duration-75"
                title="Download"
              >
                <Download className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-auto tactical-scroll">
            {!output ? (
              <div className="p-8 text-center text-white/30 text-sm font-mono">
                obfuscated output appears here
              </div>
            ) : (
              <pre className="p-3 font-mono text-xs leading-relaxed text-[#3395FF] whitespace-pre-wrap break-all">
                {output}
              </pre>
            )}
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="flex flex-wrap items-center gap-3 border border-white/10 bg-[#0A0A0A] p-4">
        <button
          data-testid="obf-run"
          onClick={run}
          disabled={busy}
          className="inline-flex items-center gap-2 border border-[#007AFF] bg-[#007AFF] hover:bg-[#3395FF] text-white px-4 py-2 text-xs uppercase tracking-[0.2em] font-bold transition-colors duration-75 disabled:opacity-50"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
          {busy ? "Encrypting…" : "Obfuscate"}
        </button>

        <div className="h-6 w-px bg-white/10" />

        <input
          data-testid="obf-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="script name…"
          className="flex-1 min-w-[180px] bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
        />
        <button
          data-testid="obf-save"
          onClick={save}
          disabled={saving || !output}
          className="inline-flex items-center gap-2 border border-white/20 hover:border-[#34C759] hover:text-[#34C759] text-white/70 px-3 py-2 text-xs uppercase tracking-[0.2em] font-bold transition-colors duration-75 disabled:opacity-30"
        >
          <Save className="w-3.5 h-3.5" />
          Save to Library
        </button>
      </div>

      {/* Info panel */}
      <div className="border border-white/10 bg-[#0A0A0A] p-4">
        <div className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold mb-2">
          WHAT EACH LAYER DOES
        </div>
        <ul className="text-xs text-white/70 space-y-1.5 leading-relaxed">
          <li>• <span className="text-white font-bold">Layer 1</span> — encrypts every string literal in your code with XOR + base64; strings only decode at runtime.</li>
          <li>• <span className="text-white font-bold">Layer 2</span> — rewrites every integer as an arithmetic expression (e.g. <span className="font-mono">42 → (10+32)</span>).</li>
          <li>• <span className="text-white font-bold">Layer 3</span> — wraps the whole thing 1-3 times in nested XOR + base64 loaders with mangled variable names.</li>
          <li>• <span className="text-white font-bold">Heavy</span> — adds junk locals and an anti-hook check that bails silently if <span className="font-mono">hookfunction</span> is present.</li>
        </ul>
        <div className="text-[10px] text-white/40 mt-3 leading-relaxed">
          ⚠ Reality: no client-side Lua obfuscator is unbreakable. Combined with the whitelist-key
          system on the Keys page (HWID lock + server-side verify), this is your own end-to-end
          protection pipeline — no external service required.
        </div>
      </div>
    </div>
  );
}
