import { useEffect, useState } from "react";
import Console from "@/components/Console";
import { botApi } from "@/lib/botApi";
import { AlertTriangle, Server, Zap, Activity, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

function fmtUptime(sec) {
  if (!sec && sec !== 0) return "—";
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${h}h ${m}m ${s}s`;
}

export default function Overview() {
  const [status, setStatus] = useState(null);
  const [commands, setCommands] = useState([]);
  const [config, setConfig] = useState(null);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      try {
        const [s, c, cfg] = await Promise.all([
          botApi.status(),
          botApi.commands(),
          botApi.config(),
        ]);
        if (!mounted) return;
        setStatus(s);
        setCommands(c.commands || []);
        setConfig(cfg);
      } catch { /* ignore */ }
    };
    load();
    const id = setInterval(load, 3000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  const running = status?.running;
  const ready = status?.runtime?.ready;

  return (
    <div className="p-4 md:p-6 space-y-6">
      {/* Section header */}
      <div>
        <div className="text-[10px] tracking-[0.25em] text-white/40 uppercase font-bold">
          SECTOR 01
        </div>
        <h1
          className="text-3xl sm:text-4xl font-black tracking-tighter uppercase text-white mt-1"
          style={{ fontFamily: "Chivo, sans-serif" }}
          data-testid="overview-title"
        >
          Command Center
        </h1>
        <p className="text-white/50 text-sm mt-1 max-w-2xl">
          Deploy or halt the moderation bot, watch the live stream, and dispatch destructive
          actions from an authorized Discord role.
        </p>
      </div>

      {!config?.bot_token_set && (
        <div
          data-testid="warning-no-token"
          className="border border-[#FFCC00]/40 bg-[#FFCC00]/[0.06] p-4 flex items-start gap-3"
        >
          <AlertTriangle className="w-4 h-4 text-[#FFCC00] mt-0.5 shrink-0" />
          <div className="flex-1 text-sm">
            <div className="text-[#FFCC00] uppercase tracking-widest text-[10px] font-bold">
              Token not verified
            </div>
            <div className="text-white/70 mt-1">
              A token is loaded from environment but has not been re-confirmed. If the bot fails to
              start with an invalid-login error, paste your Discord bot token in{" "}
              <Link to="/config" className="underline text-white">Config</Link>.
            </div>
          </div>
        </div>
      )}

      {status?.mongo_is_local && (
        <div
          data-testid="warning-local-mongo"
          className="border border-[#FF6961]/50 bg-[#FF3B30]/[0.08] p-4 flex items-start gap-3"
        >
          <AlertTriangle className="w-4 h-4 text-[#FF6961] mt-0.5 shrink-0" />
          <div className="flex-1 text-sm">
            <div className="text-[#FF6961] uppercase tracking-widest text-[10px] font-bold">
              Dashboard is using a LOCAL database
            </div>
            <div className="text-white/70 mt-1">
              Current DB host: <span className="font-mono text-white">{status.mongo_host}</span> · database: <span className="font-mono text-white">{status.db_name}</span>
              <br />
              <span className="text-white/50">
                This DB lives inside the preview container. Anything you create here <b>will NOT be visible to a Discord bot deployed on Render or bot-hosting.net</b>, and it will reset when the preview container rebuilds. To make everything persistent AND shared with your production bot, point both to the same MongoDB Atlas cluster (free tier: cloud.mongodb.com).
              </span>
            </div>
          </div>
        </div>
      )}

      {/* KPI Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi
          testid="kpi-status"
          icon={Zap}
          label="Bot Status"
          value={running ? (ready ? "Online" : "Booting…") : "Offline"}
          tone={running ? (ready ? "ok" : "warn") : "muted"}
        />
        <Kpi
          testid="kpi-uptime"
          icon={Activity}
          label="Uptime"
          value={fmtUptime(status?.uptime_seconds)}
        />
        <Kpi
          testid="kpi-guilds"
          icon={Server}
          label="Connected Guilds"
          value={status?.runtime?.guild_count ?? 0}
        />
        <Kpi
          testid="kpi-latency"
          icon={Activity}
          label="Gateway Latency"
          value={status?.runtime?.latency_ms != null ? `${status.runtime.latency_ms}ms` : "—"}
        />
      </div>

      {/* Main 12-col grid */}
      <div className="grid grid-cols-12 gap-4">
        {/* Console */}
        <div className="col-span-12 lg:col-span-8">
          <div className="h-[520px]">
            <Console />
          </div>
        </div>

        {/* Commands panel */}
        <div className="col-span-12 lg:col-span-4">
          <div className="h-[520px] flex flex-col border border-white/10 bg-[#0A0A0A]">
            <div className="px-3 py-2 border-b border-white/10 flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold">
                COMMAND REGISTRY
              </span>
              <Link
                to="/commands"
                className="text-[10px] uppercase tracking-widest text-white/50 hover:text-white flex items-center gap-1"
                data-testid="see-all-commands"
              >
                All <ArrowRight className="w-3 h-3" />
              </Link>
            </div>
            <div className="flex-1 overflow-y-auto tactical-scroll">
              {commands.map((c) => (
                <div
                  key={c.name}
                  data-testid={`cmd-row-${c.name}`}
                  className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-3 py-2.5 border-b border-white/5 hover:bg-white/[0.03]"
                >
                  <span
                    className={`font-mono text-sm ${c.destructive ? "text-[#FF6961]" : "text-white"}`}
                  >
                    /{c.name}
                  </span>
                  <span className="text-xs text-white/50 truncate">{c.description}</span>
                  <span
                    className={`text-[9px] uppercase tracking-[0.2em] font-bold ${
                      c.status === "active" ? "text-[#34C759]" : "text-white/30"
                    }`}
                  >
                    {c.status}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Kpi({ icon: Icon, label, value, tone = "default", testid }) {
  const toneCls =
    tone === "ok"
      ? "text-[#34C759]"
      : tone === "warn"
      ? "text-[#FFCC00]"
      : tone === "muted"
      ? "text-white/40"
      : "text-white";
  return (
    <div
      data-testid={testid}
      className="border border-white/10 bg-[#0A0A0A] p-4 flex flex-col hover:border-white/20 transition-colors duration-75"
    >
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-[0.25em] text-white/40 font-bold">{label}</span>
        <Icon className="w-4 h-4 text-white/30" />
      </div>
      <div className={`mt-3 text-2xl font-black tracking-tight ${toneCls}`} style={{ fontFamily: "Chivo, sans-serif" }}>
        {value}
      </div>
    </div>
  );
}
