import { useEffect, useRef, useState } from "react";
import { botApi } from "@/lib/botApi";
import { Trash2, Pause, Play } from "lucide-react";

const LEVEL_COLORS = {
  ERROR: "text-[#FF6961]",
  FAIL: "text-[#FF6961]",
  WARN: "text-[#FFCC00]",
  INFO: "text-white/80",
  READY: "text-[#34C759]",
  BOOT: "text-[#3395FF]",
  WIPE: "text-[#FF3B30]",
  CTRL: "text-white/40",
};

function classify(line) {
  const l = line.toLowerCase();
  if (l.includes("[fatal]") || l.includes("error") || l.includes("failed") || l.includes("✗")) return "ERROR";
  if (l.includes("warn")) return "WARN";
  if (l.includes("[ready]")) return "READY";
  if (l.includes("[boot]")) return "BOOT";
  if (l.includes("[wipe]") || l.includes("wipe")) return "WIPE";
  if (l.includes("[control]")) return "CTRL";
  return "INFO";
}

export default function Console() {
  const [logs, setLogs] = useState([]);
  const [cursor, setCursor] = useState(0);
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const boxRef = useRef(null);

  useEffect(() => {
    let interval;
    const tick = async () => {
      if (paused) return;
      try {
        const { logs: fresh, cursor: c } = await botApi.logs(cursor);
        if (fresh && fresh.length) {
          setLogs((prev) => [...prev, ...fresh].slice(-2000));
          setCursor(c);
        } else if (cursor === 0 && c > 0) {
          setCursor(c);
        }
      } catch { /* ignore polling errors */ }
    };
    tick();
    interval = setInterval(tick, 1200);
    return () => clearInterval(interval);
  }, [cursor, paused]);

  useEffect(() => {
    if (autoScroll && boxRef.current) {
      boxRef.current.scrollTop = boxRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  const clear = async () => {
    await botApi.clearLogs();
    setLogs([]);
    setCursor(0);
  };

  return (
    <div className="flex flex-col h-full border border-white/10 bg-black" data-testid="console-panel">
      <div className="flex items-center justify-between px-3 py-2 border-b border-white/10 bg-[#0A0A0A]">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold">
            LIVE CONSOLE
          </span>
          <span className="font-mono text-[10px] text-white/30">
            {logs.length} lines
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button
            data-testid="console-pause"
            onClick={() => setPaused((p) => !p)}
            className="p-1.5 border border-white/10 hover:border-white/30 text-white/60 hover:text-white transition-colors duration-75"
            title={paused ? "Resume" : "Pause"}
          >
            {paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
          </button>
          <button
            data-testid="console-clear"
            onClick={clear}
            className="p-1.5 border border-white/10 hover:border-[#FF3B30]/50 hover:text-[#FF6961] text-white/60 transition-colors duration-75"
            title="Clear"
          >
            <Trash2 className="w-3.5 h-3.5" />
          </button>
          <label className="flex items-center gap-1 ml-2 text-[10px] uppercase tracking-widest text-white/50 cursor-pointer">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="accent-[#007AFF]"
            />
            Follow
          </label>
        </div>
      </div>
      <div
        ref={boxRef}
        className="flex-1 overflow-y-auto tactical-scroll font-mono text-xs leading-relaxed p-3 bg-black min-h-[300px]"
        data-testid="console-output"
      >
        {logs.length === 0 && (
          <div className="text-white/30">
            <span className="text-[#34C759]">$</span> waiting for bot output…
          </div>
        )}
        {logs.map((l, i) => {
          const lvl = classify(l.line);
          const color = LEVEL_COLORS[lvl] || "text-white/80";
          const ts = l.ts?.slice(11, 19) || "";
          return (
            <div key={i} className="console-line whitespace-pre-wrap break-all">
              <span className="text-white/25">{ts}</span>{" "}
              <span className={`${color}`}>{l.line}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
