import { useEffect, useMemo, useState } from "react";
import { botApi } from "@/lib/botApi";
import { Shield, Zap, Filter } from "lucide-react";

const CATEGORY_ORDER = [
  "moderation",
  "channel",
  "role",
  "voice",
  "nickname",
  "info",
  "utility",
  "config",
  "emoji",
  "protection",
];

export default function CommandsPage() {
  const [commands, setCommands] = useState([]);
  const [q, setQ] = useState("");
  const [activeCat, setActiveCat] = useState("all");

  useEffect(() => {
    botApi.commands().then((c) => setCommands(c.commands || []));
  }, []);

  const filtered = useMemo(() => {
    return commands.filter((c) => {
      if (activeCat !== "all" && c.category !== activeCat) return false;
      if (q && !`${c.name} ${c.description}`.toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    });
  }, [commands, q, activeCat]);

  const grouped = useMemo(() => {
    const g = {};
    for (const c of filtered) {
      g[c.category] = g[c.category] || [];
      g[c.category].push(c);
    }
    return g;
  }, [filtered]);

  const total = commands.length;
  const destructiveCount = commands.filter((c) => c.destructive).length;

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <div className="text-[10px] tracking-[0.25em] text-white/40 uppercase font-bold">
            SECTOR 02
          </div>
          <h1
            className="text-3xl sm:text-4xl font-black tracking-tighter uppercase text-white mt-1"
            style={{ fontFamily: "Chivo, sans-serif" }}
            data-testid="commands-title"
          >
            Command Registry
          </h1>
          <p className="text-white/50 text-sm mt-1 max-w-2xl">
            <span className="text-white font-bold" data-testid="commands-total">{total}</span> slash commands loaded ·{" "}
            <span className="text-[#FF6961] font-bold">{destructiveCount}</span> destructive
          </p>
        </div>

        {/* search */}
        <div className="flex items-center gap-2 min-w-[240px]">
          <Filter className="w-3.5 h-3.5 text-white/40" />
          <input
            data-testid="commands-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="filter commands…"
            className="flex-1 bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-1.5 font-mono text-xs text-white placeholder:text-white/25"
          />
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex flex-wrap gap-2 border-b border-white/10 pb-3">
        <CatChip active={activeCat === "all"} onClick={() => setActiveCat("all")} count={commands.length}>
          all
        </CatChip>
        {CATEGORY_ORDER.map((cat) => {
          const count = commands.filter((c) => c.category === cat).length;
          if (!count) return null;
          return (
            <CatChip key={cat} active={activeCat === cat} onClick={() => setActiveCat(cat)} count={count}>
              {cat}
            </CatChip>
          );
        })}
      </div>

      {CATEGORY_ORDER.filter((cat) => grouped[cat]).map((cat) => (
        <div key={cat} className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-[0.25em] text-white/40 font-bold">
              /{cat}
            </span>
            <div className="h-px bg-white/10 flex-1" />
            <span className="font-mono text-[10px] text-white/30">{grouped[cat].length}</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {grouped[cat].map((c) => (
              <div
                key={c.name}
                data-testid={`cmd-card-${c.name}`}
                className={`border p-3 bg-[#0A0A0A] transition-colors duration-75 ${
                  c.destructive
                    ? "border-[#FF3B30]/40 hover:border-[#FF3B30]/70"
                    : "border-white/10 hover:border-white/25"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className={`font-mono text-sm ${c.destructive ? "text-[#FF6961]" : "text-white"}`}>
                    /{c.name}
                  </span>
                  {c.destructive ? (
                    <Shield className="w-3.5 h-3.5 text-[#FF6961]" />
                  ) : (
                    <Zap className="w-3.5 h-3.5 text-white/40" />
                  )}
                </div>
                <div className="text-xs text-white/55 mt-1.5 leading-relaxed">
                  {c.description}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}

      {filtered.length === 0 && (
        <div className="text-center py-12 text-white/30 text-sm font-mono">
          no commands match your filter
        </div>
      )}
    </div>
  );
}

function CatChip({ active, onClick, children, count }) {
  return (
    <button
      onClick={onClick}
      data-testid={`cat-chip-${children}`}
      className={`text-[10px] uppercase tracking-[0.25em] font-bold px-3 py-1.5 border transition-colors duration-75 ${
        active
          ? "border-[#007AFF] bg-[#007AFF]/10 text-white"
          : "border-white/10 text-white/50 hover:text-white hover:border-white/30"
      }`}
    >
      {children}
      <span className="font-mono ml-2 text-white/40">{count}</span>
    </button>
  );
}
