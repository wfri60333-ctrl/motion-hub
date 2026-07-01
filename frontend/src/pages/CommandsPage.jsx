import { useEffect, useState } from "react";
import { botApi } from "@/lib/botApi";
import { Shield, Zap } from "lucide-react";

export default function CommandsPage() {
  const [commands, setCommands] = useState([]);
  useEffect(() => {
    botApi.commands().then((c) => setCommands(c.commands || []));
  }, []);

  return (
    <div className="p-4 md:p-6 space-y-6">
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
          Slash commands available to the moderation bot. Only `/wipe` is active right now — the
          other 50+ moderation commands will be dispatched in the next mission.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {commands.map((c) => (
          <div
            key={c.name}
            data-testid={`cmd-card-${c.name}`}
            className={`border p-4 bg-[#0A0A0A] transition-colors duration-75 ${
              c.destructive
                ? "border-[#FF3B30]/40 hover:border-[#FF3B30]/70"
                : "border-white/10 hover:border-white/25"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className={`font-mono text-lg ${c.destructive ? "text-[#FF6961]" : "text-white"}`}>
                /{c.name}
              </span>
              {c.destructive ? (
                <Shield className="w-4 h-4 text-[#FF6961]" />
              ) : (
                <Zap className="w-4 h-4 text-white/40" />
              )}
            </div>
            <div className="text-sm text-white/60 mt-2 min-h-[36px]">{c.description}</div>
            <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/5">
              <span className="text-[9px] uppercase tracking-[0.25em] text-white/40 font-bold">
                {c.category}
              </span>
              <span
                className={`text-[9px] uppercase tracking-[0.25em] font-bold ${
                  c.status === "active" ? "text-[#34C759]" : "text-white/40"
                }`}
              >
                {c.status}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
