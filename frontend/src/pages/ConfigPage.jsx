import { useEffect, useState } from "react";
import { botApi } from "@/lib/botApi";
import { Save, KeyRound, Fingerprint, ShieldCheck, ExternalLink } from "lucide-react";
import { toast } from "sonner";

export default function ConfigPage() {
  const [config, setConfig] = useState(null);
  const [token, setToken] = useState("");
  const [appId, setAppId] = useState("");
  const [roles, setRoles] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    const c = await botApi.config();
    setConfig(c);
    setAppId(c.application_id || "");
    setRoles((c.allowed_role_ids || []).join(", "));
  };

  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      const payload = {
        application_id: appId,
        allowed_role_ids: roles
          .split(/[,\s]+/)
          .map((s) => s.trim())
          .filter(Boolean),
      };
      if (token.trim()) payload.bot_token = token.trim();
      await botApi.updateConfig(payload);
      toast.success("Configuration saved");
      setToken("");
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
          Credentials and access control for the moderation bot. Changes take effect the next time
          the bot is deployed.
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
            label="Allowed Role IDs"
            hint="Comma-separated Discord role IDs. Members with any of these roles (or Administrator) can run destructive commands like /wipe."
          >
            <textarea
              data-testid="config-roles-input"
              value={roles}
              onChange={(e) => setRoles(e.target.value)}
              rows={3}
              placeholder="e.g. 111111111111111111, 222222222222222222"
              className="w-full bg-black border border-white/15 focus:border-[#007AFF] outline-none px-3 py-2.5 font-mono text-sm text-white placeholder:text-white/25 resize-none"
            />
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
          <div className="border border-white/10 bg-[#0A0A0A] p-4 text-sm">
            <div className="text-[10px] uppercase tracking-[0.25em] text-white/40 font-bold">
              PERMISSION MODEL
            </div>
            <ul className="mt-3 space-y-2 text-white/70 text-xs leading-relaxed">
              <li>• Members with <span className="text-white">Administrator</span> can always run <span className="font-mono text-[#FF6961]">/wipe</span>.</li>
              <li>• Otherwise the member must hold one of the role IDs configured here.</li>
              <li>• The bot must have <span className="text-white">Manage Channels</span> permission in every channel it deletes.</li>
              <li>• Every destructive action is written to the <span className="text-white">Audit</span> log.</li>
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
