import { useEffect, useState } from "react";
import { botApi } from "@/lib/botApi";
import { Save, KeyRound, Fingerprint, ShieldCheck, ExternalLink, Shield, Clock, AlertTriangle, Users } from "lucide-react";
import { toast } from "sonner";

const CATEGORIES = [
  { key: "moderation", label: "Moderation", desc: "ban, kick, timeout, purge, warn, wipe, nuke…" },
  { key: "protection", label: "Script Protection", desc: "panel, whitelist, revoke, resethwid, obfuscate…" },
  { key: "channel",    label: "Channel",           desc: "lock, hide, slowmode, rename, clone…" },
  { key: "role",       label: "Role",              desc: "addrole, createrole, deleterole…" },
  { key: "voice",      label: "Voice",             desc: "vmute, deafen, disconnect, move…" },
  { key: "nickname",   label: "Nickname",          desc: "nick, resetnick" },
  { key: "config",     label: "Config",            desc: "setmodlog, autorole, welcome, perms" },
  { key: "utility",    label: "Utility",           desc: "say, embed, poll, remind" },
  { key: "emoji",      label: "Emoji",             desc: "addemoji, deleteemoji" },
];

export default function ConfigPage() {
  const [config, setConfig] = useState(null);
  const [token, setToken] = useState("");
  const [appId, setAppId] = useState("");
  const [roles, setRoles] = useState("");
  const [luaobfKey, setLuaobfKey] = useState("");
  const [perms, setPerms] = useState({}); // { category: "id1, id2" }
  const [cooldown, setCooldown] = useState(24);
  const [lockout, setLockout] = useState(5);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const c = await botApi.config();
    setConfig(c);
    setAppId(c.application_id || "");
    setRoles((c.allowed_role_ids || []).join(", "));
    const p = c.command_role_perms || {};
    const asStrings = {};
    for (const k of Object.keys(p)) asStrings[k] = (p[k] || []).join(", ");
    setPerms(asStrings);
    setCooldown(c.hwid_reset_cooldown_hours ?? 24);
    setLockout(c.hwid_mismatch_lockout ?? 5);
  };

  useEffect(() => { load(); }, []);

  const save = async () => {
    setSaving(true);
    try {
      const command_role_perms = {};
      for (const cat of Object.keys(perms)) {
        const list = (perms[cat] || "")
          .split(/[,\s]+/)
          .map((s) => s.trim())
          .filter(Boolean);
        if (list.length) command_role_perms[cat] = list;
      }
      const payload = {
        application_id: appId,
        allowed_role_ids: roles.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
        command_role_perms,
        hwid_reset_cooldown_hours: Number(cooldown) || 0,
        hwid_mismatch_lockout: Number(lockout) || 0,
      };
      if (token.trim()) payload.bot_token = token.trim();
      if (luaobfKey.trim()) payload.luaobfuscator_api_key = luaobfKey.trim();
      await botApi.updateConfig(payload);
      toast.success("Configuration saved");
      setToken("");
      setLuaobfKey("");
      await load();
    } catch (e) {
      toast.error("Failed to save configuration");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="p-4 md:p-6 space-y-6">
      <div>
        <div className="text-[10px] tracking-[0.25em] text-white/40 uppercase font-bold">
          SECTOR 03
        </div>
        <h1
          className="text-3xl sm:text-4xl font-black tracking-tighter uppercase text-white mt-1"
          style={{ fontFamily: "Chivo, sans-serif" }}
          data-testid="config-title"
        >
          Bot Configuration
        </h1>
        <p className="text-white/50 text-sm mt-1 max-w-2xl">
          Credentials, per-category role gates, HWID controls. Changes are picked up by the bot on
          the next command execution.
        </p>
      </div>

      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 lg:col-span-8 space-y-4">
          <Field
            icon={KeyRound}
            label="Bot Token"
            hint="Get this from Discord Developer Portal → your app → Bot → Reset Token. Never share it."
          >
            <input
              data-testid="config-token-input"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={config?.bot_token_set ? config.bot_token_masked : "paste bot token"}
              className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2.5 font-mono text-sm text-white placeholder:text-white/25"
            />
            <div className="text-[10px] mt-1.5 uppercase tracking-widest text-white/40">
              Current: {config?.bot_token_set ? "loaded" : "not set"}
            </div>
          </Field>

          <Field
            icon={Fingerprint}
            label="Application ID"
            hint="Your Discord application's client id (used to invite the bot)."
          >
            <input
              data-testid="config-appid-input"
              value={appId}
              onChange={(e) => setAppId(e.target.value)}
              placeholder="e.g. 1521654504045543578"
              className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2.5 font-mono text-sm text-white placeholder:text-white/25"
            />
            {appId && (
              <a
                data-testid="invite-link"
                href={`https://discord.com/oauth2/authorize?client_id=${appId}&scope=bot+applications.commands&permissions=8`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 text-[11px] uppercase tracking-[0.2em] text-[#3395FF] hover:text-[#66AAFF] mt-2 font-bold"
              >
                Open invite link <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </Field>

          <Field
            icon={ShieldCheck}
            label="Global Allowed Role IDs"
            hint="Comma-separated Discord role IDs. Members with any of these roles (or Administrator) can run every command by default. Per-category rules below narrow this further."
          >
            <textarea
              data-testid="config-roles-input"
              value={roles}
              onChange={(e) => setRoles(e.target.value)}
              rows={2}
              placeholder="e.g. 111111111111111111, 222222222222222222"
              className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2.5 font-mono text-sm text-white placeholder:text-white/25 resize-none"
            />
          </Field>

          {/* Per-category role gates */}
          <div className="border border-white/10 bg-[#0A0A0A] p-4">
            <div className="flex items-center gap-2">
              <Users className="w-4 h-4 text-white/50" />
              <span className="text-[10px] uppercase tracking-[0.25em] text-white/60 font-bold">
                Per-Category Role Gate
              </span>
            </div>
            <div className="text-xs text-white/40 mt-1 mb-3">
              Leave blank = anyone in the global allow-list above can use it.
              Set a role ID = ONLY holders of that role (plus Administrators) can run commands in
              this category. You can also configure this from Discord with{" "}
              <span className="font-mono text-white/60">/perms &lt;category&gt; &lt;role&gt;</span>.
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {CATEGORIES.map((c) => (
                <div key={c.key} className="border border-white/5 p-2.5">
                  <div className="text-[11px] font-bold uppercase tracking-widest text-white">
                    {c.label}
                  </div>
                  <div className="text-[10px] text-white/40 mb-1.5">{c.desc}</div>
                  <input
                    data-testid={`perm-${c.key}-input`}
                    value={perms[c.key] || ""}
                    onChange={(e) => setPerms({ ...perms, [c.key]: e.target.value })}
                    placeholder="role id(s), comma-separated"
                    className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-2 py-1.5 font-mono text-[11px] text-white placeholder:text-white/25"
                  />
                </div>
              ))}
            </div>
          </div>

          {/* HWID */}
          <div className="border border-white/10 bg-[#0A0A0A] p-4">
            <div className="flex items-center gap-2">
              <Clock className="w-4 h-4 text-white/50" />
              <span className="text-[10px] uppercase tracking-[0.25em] text-white/60 font-bold">
                HWID Reset & Lockout
              </span>
            </div>
            <div className="text-xs text-white/40 mt-1 mb-3">
              User self-serve HWID resets (from the Discord panel button) are rate-limited. Admin
              resets via <span className="font-mono">/resethwid</span> or the dashboard always
              bypass this cooldown.
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] uppercase tracking-widest text-white/50 font-bold">
                  User reset cooldown (hours)
                </label>
                <input
                  data-testid="hwid-cooldown-input"
                  type="number"
                  min="0"
                  value={cooldown}
                  onChange={(e) => setCooldown(e.target.value)}
                  className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-sm text-white mt-1"
                />
                <div className="text-[10px] text-white/40 mt-1">0 = disabled (unlimited resets)</div>
              </div>
              <div>
                <label className="text-[10px] uppercase tracking-widest text-white/50 font-bold flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3 text-[#FFCC00]" />
                  Auto-lockout after N mismatches
                </label>
                <input
                  data-testid="hwid-lockout-input"
                  type="number"
                  min="0"
                  value={lockout}
                  onChange={(e) => setLockout(e.target.value)}
                  className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2 font-mono text-sm text-white mt-1"
                />
                <div className="text-[10px] text-white/40 mt-1">
                  0 = disabled. Locked keys require <span className="font-mono">/unlockkey</span> or dashboard reset.
                </div>
              </div>
            </div>
          </div>

          <Field
            icon={Shield}
            label="LuaObfuscator API Key (optional)"
            hint="Optional. MOD_CTRL uses the bundled Prometheus obfuscator by default (best quality). Add a luaobfuscator.com key only if you want to use their engine as an alternative."
          >
            <input
              data-testid="config-luaobf-input"
              type="password"
              value={luaobfKey}
              onChange={(e) => setLuaobfKey(e.target.value)}
              placeholder={config?.luaobfuscator_api_key_set ? config.luaobfuscator_api_key_masked : "leave blank — uses Prometheus"}
              className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2.5 font-mono text-sm text-white placeholder:text-white/25"
            />
            <div className="text-[10px] mt-1.5 uppercase tracking-widest text-white/40">
              Current: {config?.luaobfuscator_api_key_set ? "external engine set" : "prometheus engine (recommended)"}
            </div>
          </Field>

          <div className="flex items-center gap-2">
            <button
              data-testid="config-save-btn"
              onClick={save}
              disabled={saving}
              className="inline-flex items-center gap-2 border border-[#007AFF]/70 bg-[#007AFF] hover:bg-[#3395FF] text-white px-4 py-2 text-xs uppercase tracking-[0.2em] font-bold transition-colors duration-75 disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" />
              {saving ? "Saving…" : "Save Configuration"}
            </button>
          </div>
        </div>

        <div className="col-span-12 lg:col-span-4">
          <div className="border border-white/10 bg-[#0A0A0A] p-4 text-sm sticky top-4">
            <div className="text-[10px] uppercase tracking-[0.25em] text-white/40 font-bold">
              PERMISSION MODEL
            </div>
            <ul className="mt-3 space-y-2 text-white/70 text-xs leading-relaxed">
              <li>• <span className="text-white">Administrators</span> always pass every gate.</li>
              <li>• Otherwise the member must hold one of the <span className="text-white">Global Allowed Role IDs</span>.</li>
              <li>• If a per-category role is set, the member must <span className="text-white">also</span> hold that role.</li>
              <li>• Configure from Discord with <span className="font-mono text-[#3395FF]">/perms &lt;category&gt; &lt;role&gt;</span>.</li>
              <li>• Every destructive action + every HWID event goes to the <span className="text-white">Audit</span> log.</li>
            </ul>
            <div className="mt-4 pt-3 border-t border-white/10 text-[10px] uppercase tracking-widest text-white/40 font-bold">
              How to get role IDs
            </div>
            <ul className="mt-2 space-y-1.5 text-[11px] text-white/60">
              <li>1. Discord Settings → Advanced → enable <span className="text-white">Developer Mode</span></li>
              <li>2. Server Settings → Roles → right-click a role → <span className="text-white">Copy ID</span></li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ icon: Icon, label, hint, children }) {
  return (
    <div className="border border-white/10 bg-[#0A0A0A] p-4">
      <div className="flex items-center gap-2">
        <Icon className="w-4 h-4 text-white/50" />
        <span className="text-[10px] uppercase tracking-[0.25em] text-white/60 font-bold">
          {label}
        </span>
      </div>
      <div className="text-xs text-white/40 mt-1 mb-3">{hint}</div>
      {children}
    </div>
  );
}
