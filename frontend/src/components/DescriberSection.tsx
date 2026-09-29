import type { DescriberResult } from "../lib/ws";

interface DescriberSectionProps {
  started: boolean;
  result: DescriberResult | null;
}

/**
 * Phase IV requirement 1 — renders once describer_completed arrives:
 * self-reported summary, observed summary, and mismatch notes (or "(none
 * found)"). Skipped entirely if capability_description_override was used,
 * since no describer_* events fire in that case — handled here simply by
 * never rendering anything until `started` (set by describer_started) is
 * true, which never happens on the override path.
 */
export default function DescriberSection({ started, result }: DescriberSectionProps) {
  if (!started) return null;

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/60">
      <div className="h-1.5 bg-gradient-to-r from-cyan-400 via-indigo-500 to-fuchsia-500" aria-hidden />
      <div className="p-5 sm:p-6">
        <div className="flex items-center gap-3">
          <span
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-500 to-indigo-500 text-xl"
            aria-hidden
          >
            🔍
          </span>
          <h2 className="text-lg font-semibold text-slate-50">AUT Capability Discovery</h2>
        </div>

        {!result ? (
          <div className="mt-4 flex items-center gap-3 rounded-xl bg-cyan-500/10 px-4 py-3 text-sm text-cyan-200">
            <span
              className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent"
              aria-hidden
            />
            <p className="animate-pulse">Probing the AUT and synthesizing a capability description…</p>
          </div>
        ) : (
          <div className="mt-4 grid grid-cols-1 gap-4 text-sm lg:grid-cols-3">
            <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-4">
              <h3 className="font-mono text-[11px] uppercase tracking-[0.2em] text-cyan-300">Self-reported</h3>
              <p className="mt-2 leading-relaxed text-slate-300">{result.self_reported_summary}</p>
            </div>
            <div className="rounded-xl border border-indigo-500/30 bg-indigo-500/5 p-4">
              <h3 className="font-mono text-[11px] uppercase tracking-[0.2em] text-indigo-300">Observed</h3>
              <p className="mt-2 leading-relaxed text-slate-300">{result.observed_summary}</p>
            </div>
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4">
              <h3 className="font-mono text-[11px] uppercase tracking-[0.2em] text-amber-300">Mismatch notes</h3>
              <p className="mt-2 leading-relaxed text-slate-300">{result.mismatch_notes ?? "(none found)"}</p>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
