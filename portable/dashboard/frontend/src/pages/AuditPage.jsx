import { useEffect, useState } from "react";
import { botApi } from "@/lib/botApi";
import { RefreshCcw } from "lucide-react";

export default function AuditPage() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const r = await botApi.audit();
      setRows(r.entries || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <div className="text-[10px] tracking-[0.25em] text-white/40 uppercase font-bold">
            SECTOR 04
          </div>
          <h1
            className="text-3xl sm:text-4xl font-black tracking-tighter uppercase text-white mt-1"
            style={{ fontFamily: "Chivo, sans-serif" }}
            data-testid="audit-title"
          >
            Audit Trail
          </h1>
          <p className="text-white/50 text-sm mt-1 max-w-2xl">
            Every destructive moderation action logged with actor, guild, and outcome.
          </p>
        </div>
        <button
          data-testid="audit-refresh"
          onClick={load}
          className="inline-flex items-center gap-2 border border-white/15 hover:border-white/40 text-white/70 hover:text-white px-3 py-1.5 text-[10px] uppercase tracking-[0.2em] font-bold transition-colors duration-75"
        >
          <RefreshCcw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      <div className="border border-white/10 bg-[#0A0A0A] overflow-hidden">
        <div className="grid grid-cols-[130px_130px_1fr_1fr_120px] px-3 py-2 border-b border-white/10 text-[10px] uppercase tracking-[0.25em] text-white/40 font-bold">
          <span>Timestamp</span>
          <span>Action</span>
          <span>Guild</span>
          <span>Actor</span>
          <span className="text-right">Outcome</span>
        </div>
        {rows.length === 0 ? (
          <div data-testid="audit-empty" className="px-3 py-10 text-center text-white/30 text-sm font-mono">
            no events logged yet — run <span className="text-[#FF6961]">/wipe</span> to see it here
          </div>
        ) : (
          rows.map((r) => {
            const ts = new Date(r.timestamp);
            return (
              <div
                key={r.id}
                data-testid={`audit-row-${r.id}`}
                className="grid grid-cols-[130px_130px_1fr_1fr_120px] px-3 py-2.5 border-b border-white/5 text-xs hover:bg-white/[0.03]"
              >
                <span className="font-mono text-white/50">
                  {ts.toLocaleDateString()} {ts.toLocaleTimeString()}
                </span>
                <span className="font-mono text-[#FF6961]">{r.action}</span>
                <span className="text-white/80 truncate">{r.guild_name}</span>
                <span className="text-white/80 truncate">{r.actor_name}</span>
                <span className="text-right font-mono text-white/60">
                  {r.details?.deleted != null
                    ? `${r.details.deleted}/${(r.details.deleted || 0) + (r.details.failed || 0)}`
                    : "—"}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
