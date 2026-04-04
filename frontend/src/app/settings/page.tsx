"use client";
import { useState, useEffect } from "react";
import Sidebar from "@/components/Sidebar";
import MobileNav from "@/components/MobileNav";
import { apiFetch } from "@/lib/api";
import { useReadOnly } from "@/lib/useReadOnly";
import { Save } from "lucide-react";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const readOnly = useReadOnly();

  useEffect(() => {
    apiFetch("/api/settings").then(setSettings).catch(console.error);
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      await apiFetch("/api/settings", { method: "POST", body: JSON.stringify(settings) });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  };

  const updateField = (key: string, value: unknown) => {
    setSettings((prev) => ({ ...(prev ?? {}), [key]: value }));
  };

  return (
    <div className="flex h-screen bg-[#050505] overflow-hidden">
      <Sidebar />
      <main className="flex-1 flex flex-col min-h-0 overflow-y-auto mobile-pb">
        <header className="h-11 shrink-0 border-b border-cyan-900/20 bg-[#0A0F0D]/90 flex items-center px-3 md:px-4 gap-2 md:gap-3">
          <span className="text-xs font-bold tracking-[0.25em] uppercase neon-text-cyan mono">Settings</span>
          <div className="ml-auto flex items-center gap-2">
            {readOnly && (
              <span className="px-1.5 py-0.5 rounded border border-amber-500/30 bg-amber-500/10 text-[8px] font-bold text-amber-400 mono tracking-wider">LIVE VIEW</span>
            )}
            {!readOnly && (
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 px-3 py-1 bg-cyan-500/15 border border-cyan-500/30 rounded text-[10px] mono text-cyan-400 hover:bg-cyan-500/25 transition-colors disabled:opacity-50"
              >
                <Save size={11} />
                {saved ? "Saved!" : saving ? "Saving..." : "Save"}
              </button>
            )}
          </div>
        </header>

        <div className="p-3 md:p-6 max-w-2xl space-y-4 md:space-y-6">
          {settings === null ? (
            <p className="text-slate-600 mono text-sm">Loading settings...</p>
          ) : (
            <>
              <Section title="Risk Management">
                <Field label="Max Positions" type="number" value={String(settings.max_positions ?? "")} onChange={(v) => updateField("max_positions", Number(v))} disabled={readOnly} />
                <Field label="Max Portfolio Pct per Trade" type="number" value={String(settings.max_portfolio_pct ?? "")} onChange={(v) => updateField("max_portfolio_pct", Number(v))} disabled={readOnly} />
                <Field label="Daily Loss Limit USD" type="number" value={String(settings.daily_loss_limit_usd ?? "")} onChange={(v) => updateField("daily_loss_limit_usd", Number(v))} disabled={readOnly} />
                <Field label="Max Drawdown Pct" type="number" value={String(settings.max_drawdown_pct ?? "")} onChange={(v) => updateField("max_drawdown_pct", Number(v))} disabled={readOnly} />
              </Section>

              <Section title="Exit Rules">
                <Field label="Stop Loss %" type="number" value={String(settings.stop_loss_pct ?? "")} onChange={(v) => updateField("stop_loss_pct", Number(v))} disabled={readOnly} />
                <Field label="Trailing Activate %" type="number" value={String(settings.trailing_activate_pct ?? "")} onChange={(v) => updateField("trailing_activate_pct", Number(v))} disabled={readOnly} />
                <Field label="Trailing Distance %" type="number" value={String(settings.trailing_distance_pct ?? "")} onChange={(v) => updateField("trailing_distance_pct", Number(v))} disabled={readOnly} />
                <Field label="Take Profit T1 %" type="number" value={String(settings.take_profit_t1_pct ?? "")} onChange={(v) => updateField("take_profit_t1_pct", Number(v))} disabled={readOnly} />
                <Field label="Take Profit T2 %" type="number" value={String(settings.take_profit_t2_pct ?? "")} onChange={(v) => updateField("take_profit_t2_pct", Number(v))} disabled={readOnly} />
                <Field label="Time Exit Hours" type="number" value={String(settings.time_exit_hours ?? "")} onChange={(v) => updateField("time_exit_hours", Number(v))} disabled={readOnly} />
              </Section>

              <Section title="Agent Thresholds">
                <Field label="Min Watcher Score" type="number" value={String(settings.min_watcher_score ?? "")} onChange={(v) => updateField("min_watcher_score", Number(v))} disabled={readOnly} />
                <Field label="Min TA Score" type="number" value={String(settings.min_ta_score ?? "")} onChange={(v) => updateField("min_ta_score", Number(v))} disabled={readOnly} />
                <Field label="Min Posterior (Bayesian)" type="number" value={String(settings.min_posterior ?? "")} onChange={(v) => updateField("min_posterior", Number(v))} disabled={readOnly} />
              </Section>
            </>
          )}
        </div>
      </main>
      <MobileNav />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="panel p-4 space-y-3">
      <h2 className="text-[10px] mono font-semibold text-cyan-500 tracking-widest uppercase border-b border-white/5 pb-2">{title}</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">{children}</div>
    </div>
  );
}

function Field({ label, type, value, onChange, disabled }: { label: string; type: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[9px] mono text-slate-600 uppercase">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={label}
        title={label}
        disabled={disabled}
        className={`bg-[#0d1410] border border-white/10 rounded px-2 py-1.5 text-[11px] mono text-slate-300 focus:border-cyan-500/40 focus:outline-none ${disabled ? "opacity-60 cursor-not-allowed" : ""}`}
      />
    </div>
  );
}
