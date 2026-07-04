import { useEffect, useState } from "react";
import { api } from "@/lib/botApi";
import { toast } from "sonner";
import { Plus, Trash2, Layers, Copy, X, ArrowRight, FileCode, Pencil, Save, Loader2 } from "lucide-react";

export default function LoadersPage() {
  const [loaders, setLoaders] = useState([]);
  const [scripts, setScripts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", description: "" });
  const [editing, setEditing] = useState(null); // { script_id, name, slug, level, source, note }
  const backendUrl = process.env.REACT_APP_BACKEND_URL;

  const load = async () => {
    setLoading(true);
    try {
      const [L, S] = await Promise.all([api.get("/loaders"), api.get("/scripts")]);
      setLoaders(L.data.loaders || []);
      setScripts(S.data.scripts || []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const startEdit = async (script) => {
    // Fetch full source (list endpoint strips it)
    try {
      const r = await api.get(`/scripts/${script.id}`);
      setEditing({
        script_id: script.id,
        name: r.data.name || script.name,
        slug: r.data.slug || script.slug || "",
        level: r.data.level || "medium",
        source: r.data.source || "",
        note: r.data.note || "",
      });
    } catch (e) {
      toast.error("Could not load script source");
    }
  };

  const saveEdit = async () => {
    if (!editing) return;
    const t = toast.loading("Re-obfuscating…");
    try {
      const body = {
        name: editing.name,
        slug: editing.slug,
        level: editing.level,
        source: editing.source,
        note: editing.note,
      };
      const r = await api.put(`/scripts/${editing.script_id}`, body);
      toast.dismiss(t);
      toast.success(r.data.reobfuscated ? "Saved + re-obfuscated" : "Saved");
      setEditing(null);
      await load();
    } catch (e) {
      toast.dismiss(t);
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const create = async () => {
    if (!form.name.trim()) { toast.error("Name required"); return; }
    setCreating(true);
    try {
      await api.post("/loaders", form);
      toast.success("Loader created");
      setForm({ name: "", description: "" });
      await load();
    } catch (e) { toast.error("Failed"); } finally { setCreating(false); }
  };

  const remove = async (id) => {
    if (!window.confirm("Delete loader? Scripts will be unlinked but not deleted.")) return;
    await api.delete(`/loaders/${id}`);
    toast.success("Deleted");
    await load();
  };

  const attach = async (loaderId, scriptId, slug) => {
    if (!slug || !slug.trim()) { toast.error("Slug required (e.g. 'aimbot')"); return; }
    try {
      await api.post(`/loaders/${loaderId}/scripts`, { script_id: scriptId, slug: slug.trim() });
      toast.success("Attached");
      await load();
    } catch (e) { toast.error(e?.response?.data?.detail || "Failed"); }
  };

  const detach = async (loaderId, scriptId) => {
    await api.delete(`/loaders/${loaderId}/scripts/${scriptId}`);
    toast.success("Removed");
    await load();
  };

  const copyUrl = async (url, label) => {
    await navigator.clipboard.writeText(url);
    toast.success(`${label} URL copied`);
  };

  const unattached = scripts.filter((s) => !s.loader_id);

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div>
        <div className="text-[10px] tracking-[0.25em] text-white/40 uppercase font-bold">
          SECTOR 08
        </div>
        <h1
          className="text-3xl sm:text-4xl font-black tracking-tighter uppercase text-white mt-1"
          style={{ fontFamily: "Chivo, sans-serif" }}
          data-testid="loaders-title"
        >
          Loaders
        </h1>
        <p className="text-white/50 text-sm mt-1 max-w-2xl">
          Group multiple scripts under one product. One key = access to every script inside the
          loader. Three loading modes generated for free: menu, bundle, and individual URLs.
        </p>
      </div>

      {/* Create */}
      <div className="border border-white/10 bg-[#0A0A0A] p-4 space-y-3">
        <div className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold">
          CREATE LOADER
        </div>
        <div className="grid grid-cols-1 md:grid-cols-[1fr_2fr_auto] gap-2">
          <input
            data-testid="loader-name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="loader name"
            className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
          />
          <input
            data-testid="loader-desc"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="description (optional)"
            className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
          />
          <button
            data-testid="loader-create"
            onClick={create}
            disabled={creating}
            className="inline-flex items-center gap-2 border border-[#34C759] bg-[#34C759]/10 hover:bg-[#34C759]/20 text-[#34C759] px-4 py-2 text-xs uppercase tracking-[0.2em] font-bold transition-colors duration-75 disabled:opacity-50"
          >
            <Plus className="w-3.5 h-3.5" /> New Loader
          </button>
        </div>
      </div>

      {/* List */}
      {loaders.length === 0 ? (
        <div className="border border-white/10 bg-[#0A0A0A] px-3 py-10 text-center text-white/30 text-sm font-mono">
          {loading ? "loading…" : "no loaders yet — create one above to group your scripts"}
        </div>
      ) : (
        loaders.map((L) => (
          <div key={L.id} className="border border-white/10 bg-[#0A0A0A]" data-testid={`loader-${L.id}`}>
            <div className="flex items-center justify-between p-4 border-b border-white/10">
              <div className="flex items-center gap-3 min-w-0">
                <Layers className="w-4 h-4 text-[#007AFF] shrink-0" />
                <div className="min-w-0">
                  <div className="text-white font-bold uppercase tracking-tight truncate">{L.name}</div>
                  <div className="text-[10px] font-mono text-white/40 truncate">id: {L.id}</div>
                </div>
              </div>
              <button
                onClick={() => remove(L.id)}
                className="p-1.5 border border-white/10 hover:border-[#FF3B30]/50 hover:text-[#FF6961] text-white/60 transition-colors duration-75"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>

            {/* 3 loading modes */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2 p-4 border-b border-white/10">
              <UrlMode
                title="MENU MODE"
                subtitle="Loader:load('slug')"
                url={`${backendUrl}/api/loader/${L.id}.lua`}
                onCopy={copyUrl}
              />
              <UrlMode
                title="BUNDLE MODE"
                subtitle="loads everything at once"
                url={`${backendUrl}/api/loader/${L.id}/bundle.lua`}
                onCopy={copyUrl}
              />
              <UrlMode
                title="INDIVIDUAL MODE"
                subtitle="one URL per script"
                url={`${backendUrl}/api/loader/${L.id}/<slug>.lua`}
                onCopy={copyUrl}
              />
            </div>

            {/* Attached scripts */}
            <div className="p-4">
              <div className="text-[10px] uppercase tracking-[0.25em] text-white/50 font-bold mb-2">
                SCRIPTS IN THIS LOADER ({(L.scripts || []).length})
              </div>
              {(L.scripts || []).length === 0 ? (
                <div className="text-xs text-white/40 py-3">No scripts attached yet.</div>
              ) : (
                (L.scripts || []).map((s) => (
                  <div key={s.id} className="grid grid-cols-[auto_1fr_auto_auto_auto_auto_auto] items-center gap-3 py-2 border-b border-white/5 text-xs">
                    <FileCode className="w-3.5 h-3.5 text-white/40" />
                    <span className={`truncate ${s.enabled === false ? "text-white/40 line-through" : "text-white"}`}>{s.name}</span>
                    <span className="font-mono text-[#3395FF]">/{s.slug}</span>
                    <span className={`font-mono text-[10px] ${
                      s.level === "heavy" ? "text-[#FF6961]" : s.level === "medium" ? "text-[#3395FF]" : "text-white/50"
                    }`}>{(s.level||"?").toUpperCase()}</span>
                    <button
                      onClick={() => startEdit(s)}
                      className="p-1 border border-white/10 hover:border-[#3395FF]/60 hover:text-[#3395FF] text-white/60"
                      title="Edit source + re-obfuscate"
                      data-testid={`script-edit-${s.id}`}
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                    <button
                      onClick={() => copyUrl(`${backendUrl}/api/loader/${L.id}/${s.slug}.lua`, "Individual")}
                      className="p-1 border border-white/10 hover:border-white/30 text-white/60 hover:text-white"
                      title="Copy individual URL"
                    >
                      <Copy className="w-3 h-3" />
                    </button>
                    <button
                      onClick={() => detach(L.id, s.id)}
                      className="p-1 border border-white/10 hover:border-[#FF3B30]/50 hover:text-[#FF6961] text-white/60"
                      title="Remove from loader"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))
              )}

              {/* Attach new */}
              {unattached.length > 0 && (
                <AttachRow loader={L} scripts={unattached} onAttach={attach} />
              )}

              {/* One-shot upload + obfuscate + attach */}
              <UploadRow loader={L} onDone={load} />
            </div>
          </div>
        ))
      )}

      {editing && (
        <div
          className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4"
          onClick={() => setEditing(null)}
        >
          <div
            className="bg-[#0A0A0A] border border-white/15 w-full max-w-3xl max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
            data-testid="edit-script-modal"
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/10">
              <div>
                <div className="text-[10px] uppercase tracking-[0.25em] text-white/40 font-bold">
                  EDIT SCRIPT
                </div>
                <div className="text-white text-sm font-mono">{editing.name}</div>
              </div>
              <button
                onClick={() => setEditing(null)}
                className="p-1.5 border border-white/10 hover:border-white/30 text-white/60 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 space-y-3 overflow-y-auto tactical-scroll">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                <input
                  value={editing.name}
                  onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                  placeholder="script name"
                  className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white"
                  data-testid="edit-name"
                />
                <input
                  value={editing.slug}
                  onChange={(e) => setEditing({ ...editing, slug: e.target.value })}
                  placeholder="slug"
                  className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white"
                  data-testid="edit-slug"
                />
                <select
                  value={editing.level}
                  onChange={(e) => setEditing({ ...editing, level: e.target.value })}
                  className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white"
                  data-testid="edit-level"
                >
                  <option value="light">Light</option>
                  <option value="medium">Medium</option>
                  <option value="heavy">Heavy</option>
                </select>
              </div>
              <textarea
                value={editing.source}
                onChange={(e) => setEditing({ ...editing, source: e.target.value })}
                rows={20}
                placeholder="paste new source Lua here"
                className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-[11px] text-white leading-relaxed resize-y min-h-[240px]"
                data-testid="edit-source"
              />
              <input
                value={editing.note}
                onChange={(e) => setEditing({ ...editing, note: e.target.value })}
                placeholder="internal note (optional)"
                className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white"
                data-testid="edit-note"
              />
              <div className="text-[10px] text-white/40">
                Saving will re-run Prometheus obfuscation with the selected level. Every existing
                loader / verify URL keeps working — no key or panel needs to be regenerated.
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 px-4 py-3 border-t border-white/10">
              <button
                onClick={() => setEditing(null)}
                className="border border-white/15 hover:border-white/40 text-white/70 hover:text-white px-3 py-1.5 text-[11px] uppercase tracking-widest font-bold"
              >
                Cancel
              </button>
              <button
                onClick={saveEdit}
                className="inline-flex items-center gap-2 border border-[#007AFF] bg-[#007AFF]/10 hover:bg-[#007AFF]/20 text-[#007AFF] px-4 py-1.5 text-[11px] uppercase tracking-widest font-bold"
                data-testid="edit-save"
              >
                <Save className="w-3.5 h-3.5" />
                Save + Re-Obfuscate
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function UploadRow({ loader, onDone }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [level, setLevel] = useState("heavy");
  const [busy, setBusy] = useState(false);

  const upload = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    if (!name.trim() || !slug.trim()) { toast.error("Name and slug required first"); e.target.value=""; return; }
    setBusy(true);
    try {
      const code = await f.text();
      const r = await api.post(`/loaders/${loader.id}/upload`, {
        name: name.trim(), slug: slug.trim(), level, code,
      });
      toast.success(`Obfuscated + attached (×${(r.data.script.output_bytes/Math.max(1,r.data.script.source_bytes)).toFixed(1)})`);
      setName(""); setSlug("");
      await onDone();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Upload failed");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-[1fr_140px_120px_auto] gap-2 mt-2 pt-2 border-t border-white/10">
      <input value={name} onChange={(e) => setName(e.target.value)}
        placeholder="script name"
        className="bg-black border border-white/15 focus:border-[#34C759] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30" />
      <input value={slug} onChange={(e) => setSlug(e.target.value)}
        placeholder="slug"
        className="bg-black border border-white/15 focus:border-[#34C759] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30" />
      <select value={level} onChange={(e) => setLevel(e.target.value)}
        className="bg-black border border-white/15 focus:border-[#34C759] outline-none px-3 py-2 font-mono text-xs text-white">
        <option value="light">Light</option>
        <option value="medium">Medium</option>
        <option value="heavy">Heavy</option>
      </select>
      <label className={`inline-flex items-center justify-center gap-1 border border-[#34C759] bg-[#34C759]/10 hover:bg-[#34C759]/20 text-[#34C759] px-3 py-2 text-[10px] uppercase tracking-widest font-bold cursor-pointer transition-colors duration-75 ${busy ? "opacity-50 pointer-events-none" : ""}`}>
        {busy ? "Obfuscating…" : "↑ Upload .lua"}
        <input type="file" accept=".lua,.txt" className="hidden" onChange={upload} disabled={busy} />
      </label>
    </div>
  );
}

function UrlMode({ title, subtitle, url, onCopy }) {
  return (
    <div className="border border-white/10 bg-black p-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] uppercase tracking-[0.2em] text-white/60 font-bold">
          {title}
        </span>
        <button
          onClick={() => onCopy(url, title)}
          className="p-1 border border-white/10 hover:border-white/40 text-white/60 hover:text-white transition-colors duration-75"
        >
          <Copy className="w-3 h-3" />
        </button>
      </div>
      <div className="text-[10px] text-white/40 mt-1">{subtitle}</div>
      <div className="mt-2 font-mono text-[10px] text-[#3395FF] break-all">{url}</div>
    </div>
  );
}

function AttachRow({ loader, scripts, onAttach }) {
  const [scriptId, setScriptId] = useState("");
  const [slug, setSlug] = useState("");
  return (
    <div className="grid grid-cols-[1fr_140px_auto] gap-2 mt-3 pt-3 border-t border-white/10">
      <select
        value={scriptId}
        onChange={(e) => setScriptId(e.target.value)}
        className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white"
      >
        <option value="">— add a script —</option>
        {scripts.map((s) => (
          <option key={s.id} value={s.id}>{s.name}</option>
        ))}
      </select>
      <input
        value={slug}
        onChange={(e) => setSlug(e.target.value)}
        placeholder="slug"
        className="bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-xs text-white placeholder:text-white/30"
      />
      <button
        onClick={() => { if (scriptId) { onAttach(loader.id, scriptId, slug); setScriptId(""); setSlug(""); } }}
        disabled={!scriptId || !slug}
        className="inline-flex items-center gap-1 border border-white/20 hover:border-white/40 text-white px-3 py-2 text-[10px] uppercase tracking-widest font-bold disabled:opacity-30"
      >
        Attach <ArrowRight className="w-3 h-3" />
      </button>
    </div>
  );
}
