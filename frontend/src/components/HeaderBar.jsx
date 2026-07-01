import { useEffect, useState } from "react";
import { botApi } from "@/lib/botApi";
import { Power, Radio, Loader2 } from "lucide-react";
import { toast } from "sonner";

function fmtUptime(sec) {
  if (!sec && sec !== 0) return "—";
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function HeaderBar() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      setStatus(await botApi.status());
    } catch (e) {
      // ignore
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 2500);
    return () => clearInterval(id);
  }, []);

  const running = status?.running;
  const ready = status?.runtime?.ready;
  const user = status?.runtime?.user;
  const guilds = status?.runtime?.guild_count ?? 0;
  const latency = status?.runtime?.latency_ms;

  const doStart = async () => {
    setBusy(true);
    try {
      await botApi.start();
      toast.success("Boot sequence initiated");
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to start bot");
    } finally {
      setBusy(false);
    }
  };
  const doStop = async () => {
    setBusy(true);
    try {
      await botApi.stop();
      toast.success("Bot halted");
      await load();
    } catch (e) {
      toast.error("Failed to stop bot");
    } finally {
      setBusy(false);
    }
  };

  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-[#050505]/95 backdrop-blur-sm">
      <div className="flex items-center gap-4 px-4 md:px-6 py-3">
        <div className="flex items-center gap-2 shrink-0">
          <span className="font-mono text-[#34C759] text-lg" data-testid="brand-logo">&gt;_</span>
          <span
            className="font-black tracking-tighter uppercase text-white text-lg md:text-xl"
            style={{ fontFamily: "Chivo, sans-serif" }}
          >
            MOD_CTRL
          </span>
          <span className="hidden sm:inline text-white/30 text-xs tracking-[0.2em] uppercase ml-2 font-mono">
            /discord-mod-bot
          </span>
        </div>

        {/* live stats strip */}
        <div className="hidden md:flex items-center gap-6 ml-6 text-xs font-mono">
          <Stat label="STATUS" value={running ? (ready ? "ONLINE" : "STARTING") : "OFFLINE"} tone={running ? (ready ? "ok" : "warn") : "muted"} testid="hdr-status" />
          <Stat label="UPTIME" value={fmtUptime(status?.uptime_seconds)} testid="hdr-uptime" />
          <Stat label="GUILDS" value={guilds} testid="hdr-guilds" />
          <Stat label="LATENCY" value={latency != null ? `${latency}ms` : "—"} testid="hdr-latency" />
          {user && <Stat label="AS" value={user} testid="hdr-user" />}
        </div>

        <div className="flex-1" />

        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${ready ? "bg-[#34C759] pulse-live" : running ? "bg-[#FFCC00]" : "bg-white/20"}`}
            data-testid="status-dot"
          />
          {running ? (
            <button
              data-testid="stop-bot-button"
              disabled={busy}
              onClick={doStop}
              className="inline-flex items-center gap-2 border border-[#FF3B30]/70 bg-[#FF3B30]/10 hover:bg-[#FF3B30]/20 text-[#FF6961] px-3 py-1.5 text-xs uppercase tracking-[0.2em] font-bold transition-colors duration-75 disabled:opacity-50"
            >
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Power className="w-3.5 h-3.5" />}
              Halt
            </button>
          ) : (
            <button
              data-testid="start-bot-button"
              disabled={busy}
              onClick={doStart}
              className="inline-flex items-center gap-2 border border-[#34C759]/70 bg-[#34C759]/10 hover:bg-[#34C759]/20 text-[#34C759] px-3 py-1.5 text-xs uppercase tracking-[0.2em] font-bold transition-colors duration-75 disabled:opacity-50"
            >
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Radio className="w-3.5 h-3.5" />}
              Deploy
            </button>
          )}
        </div>
      </div>
    </header>
  );
}

function Stat({ label, value, tone = "default", testid }) {
  const toneCls =
    tone === "ok"
      ? "text-[#34C759]"
      : tone === "warn"
      ? "text-[#FFCC00]"
      : tone === "muted"
      ? "text-white/40"
      : "text-white/80";
  return (
    <div className="flex flex-col leading-tight">
      <span className="text-[9px] tracking-[0.25em] text-white/40 font-bold">{label}</span>
      <span data-testid={testid} className={`${toneCls} font-mono`}>
        {value}
      </span>
    </div>
  );
}
