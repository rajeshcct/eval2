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
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="text-lg font-semibold text-slate-100">AUT Capability Discovery</h2>

      {!result ? (
        <p className="mt-2 animate-pulse text-sm text-slate-400">
          Probing the AUT and synthesizing a capability description…
        </p>
      ) : (
        <div className="mt-3 flex flex-col gap-3 text-sm">
          <div>
            <h3 className="font-medium text-slate-200">Self-reported</h3>
            <p className="mt-1 text-slate-400">{result.self_reported_summary}</p>
          </div>
          <div>
            <h3 className="font-medium text-slate-200">Observed</h3>
            <p className="mt-1 text-slate-400">{result.observed_summary}</p>
          </div>
          <div>
            <h3 className="font-medium text-slate-200">Mismatch notes</h3>
            <p className="mt-1 text-slate-400">{result.mismatch_notes ?? "(none found)"}</p>
          </div>
        </div>
      )}
    </section>
  );
}
