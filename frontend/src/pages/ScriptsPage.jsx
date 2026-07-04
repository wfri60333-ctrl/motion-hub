import { useEffect, useState } from "react";
import { api } from "@/lib/botApi";
import { toast } from "sonner";
import { Copy, Download, Trash2, FileCode, Power, PowerOff } from "lucide-react";

export default function ScriptsPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await api.get("/scripts");
      setRows(r.data.scripts || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const download = async (id, name, level) => {
    const r = await api.get(`/scripts/${id}`);
    const blob = new Blob([r.data.obfuscated], { type: "text/x-lua" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name || "script"}_${level}.lua`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copy = async (id) => {
    const r = await api.get(`/scripts/${id}`);
    await navigator.clipboard.writeText(r.data.obfuscated);
    toast.success("Copied to clipboard");
  };

  const remove = async (id) => {
    if (!window.confirm("Delete this script?")) return;
    await api.delete(`/scripts/${id}`);
    toast.success("Deleted");
    await load();
  };

  const toggle = async (s) => {
    const next = !(s.enabled !== false);
    await api.post(`/scripts/${s.id}/toggle`, { enabled: next });
    toast.success(next ? "Enabled — script is live" : "🛑 Kill switch ON — no verify succeeds until re-enabled");
    await load();
  };

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div>
        <div className="text-[10px] tracking-[0.25em] text-white/40 uppercase font-bold">
          SECTOR 06
        </div>
        <h1
          className="text-3xl sm:text-4xl font-black tracking-tighter uppercase text-white mt-1"
          style={{ fontFamily: "Chivo, sans-serif" }}
          data-testid="scripts-title"
        >
          Script Library
        </h1>
        <p className="text-white/50 text-sm mt-1 max-w-2xl">
          Obfuscated scripts you've saved. Copy or re-download anytime.
        </p>
      </div>

      <div className="border border-white/10 bg-[#0A0A0A] overflow-hidden">
        <div className="grid grid-cols-[1fr_100px_100px_130px_140px] px-3 py-2 border-b border-white/10 text-[10px] uppercase tracking-[0.25em] text-white/40 font-bold">
          <span>Name</span>
          <span>Level</span>
          <span className="text-right">Size</span>
          <span>Created</span>
          <span className="text-right">Actions</span>
        </div>
        {rows.length === 0 ? (
          <div className="px-3 py-10 text-center text-white/30 text-sm font-mono">
            {loading ? "loading…" : "no scripts yet — obfuscate and save one from the Obfuscator page"}
          </div>
        ) : (
          rows.map((s) => {
            const ts = new Date(s.created_at);
            return (
              <div
                key={s.id}
                data-testid={`script-row-${s.id}`}
                className="grid grid-cols-[1fr_100px_100px_130px_140px] px-3 py-2.5 border-b border-white/5 text-xs items-center hover:bg-white/[0.03]"
              >
                <div className="flex items-center gap-2 min-w-0">
                  <FileCode className="w-3.5 h-3.5 text-white/40 shrink-0" />
                  <span className={`truncate ${s.enabled === false ? "text-white/40 line-through" : "text-white"}`}>{s.name}</span>
                  {s.enabled === false && <span className="text-[9px] font-bold text-[#FF6961] uppercase tracking-widest">KILL</span>}
                </div>
                <span
                  className={`font-mono uppercase text-[10px] ${
                    s.level === "heavy" ? "text-[#FF6961]" : s.level === "medium" ? "text-[#3395FF]" : "text-white/60"
                  }`}
                >
                  {s.level}
                </span>
                <span className="font-mono text-white/50 text-right">{s.output_bytes}b</span>
                <span className="text-white/50 font-mono">{ts.toLocaleDateString()}</span>
                <div className="flex items-center gap-1 justify-end">
                  <button
                    onClick={() => toggle(s)}
                    className={`p-1.5 border transition-colors duration-75 ${
                      s.enabled === false
                        ? "border-[#FF3B30]/50 text-[#FF6961]"
                        : "border-white/10 hover:border-[#34C759]/40 text-white/60 hover:text-[#34C759]"
                    }`}
                    title={s.enabled === false ? "Kill switch ON — click to re-enable" : "Kill switch — click to disable"}
                    data-testid={`script-toggle-${s.id}`}
                  >
                    {s.enabled === false ? <PowerOff className="w-3.5 h-3.5" /> : <Power className="w-3.5 h-3.5" />}
                  </button>
                  <button
                    onClick={() => copy(s.id)}
                    className="p-1.5 border border-white/10 hover:border-white/30 text-white/60 hover:text-white transition-colors duration-75"
                    title="Copy"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => download(s.id, s.name, s.level)}
                    className="p-1.5 border border-white/10 hover:border-white/30 text-white/60 hover:text-white transition-colors duration-75"
                    title="Download"
                  >
                    <Download className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => remove(s.id)}
                    className="p-1.5 border border-white/10 hover:border-[#FF3B30]/50 hover:text-[#FF6961] text-white/60 transition-colors duration-75"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
