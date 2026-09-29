import { CATEGORY_ORDER, type CategoryLiveState } from "../lib/liveState";
import { themeFor } from "./categoryTheme";

interface OverallProgressProps {
  categories: Record<string, CategoryLiveState>;
}

const LABELS: Record<string, string> = {
  functionality: "Functionality",
  security: "Security",
  compliance: "Compliance",
};

function statusLabel(status: CategoryLiveState["status"]): string {
  switch (status) {
    case "pending":
      return "Pending";
    case "running":
      return "Running";
    case "broken":
      return "Broken";
    case "robust_within_tested_range":
      return "Robust";
  }
}

function stepStyle(status: CategoryLiveState["status"]): { card: string; circle: string; text: string } {
  switch (status) {
    case "pending":
      return {
        card: "border-slate-800 bg-slate-900/40",
        circle: "bg-slate-800 text-slate-500 grayscale",
        text: "text-slate-500",
      };
    case "running":
      return {
        card: "border-sky-500/50 bg-sky-500/10 shadow-lg shadow-sky-900/30",
        circle: "bg-gradient-to-br from-sky-500 to-indigo-500 text-white",
        text: "text-sky-300",
      };
    case "broken":
      return {
        card: "border-red-500/40 bg-red-500/10",
        circle: "bg-red-500/20 text-red-300 ring-2 ring-red-500/50",
        text: "text-red-300",
      };
    case "robust_within_tested_range":
      return {
        card: "border-emerald-500/40 bg-emerald-500/10",
        circle: "bg-emerald-500/20 text-emerald-300 ring-2 ring-emerald-500/50",
        text: "text-emerald-300",
      };
  }
}

/**
 * Phase IV requirement 3 — an overall progress indicator showing which of
 * the 3 categories are done / running / pending.
 */
export default function OverallProgress({ categories }: OverallProgressProps) {
  const total = CATEGORY_ORDER.length;
  const done = CATEGORY_ORDER.filter((c) => {
    const s = categories[c].status;
    return s === "broken" || s === "robust_within_tested_range";
  }).length;
  const anyRunning = CATEGORY_ORDER.some((c) => categories[c].status === "running");
  const pct = Math.round((done / total) * 100);

  return (
    <div className="rounded-2xl border border-slate-800 bg-gradient-to-br from-slate-900/80 to-slate-950/80 p-5 sm:p-6">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-[11px] uppercase tracking-[0.2em] text-slate-400">Overall progress</span>
        <span className="text-sm text-slate-300">
          <span className="font-semibold text-slate-50">{done}</span> of {total} categories complete
        </span>
      </div>

      <div className="h-2.5 overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full rounded-full bg-gradient-to-r from-indigo-500 via-fuchsia-500 to-emerald-400 transition-all duration-700 ${
            anyRunning ? "animate-pulse" : ""
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {CATEGORY_ORDER.map((category) => {
          const cat = categories[category];
          const style = stepStyle(cat.status);
          const theme = themeFor(category);
          const glyph =
            cat.status === "broken" ? "✕" : cat.status === "robust_within_tested_range" ? "✓" : theme.icon;
          return (
            <div key={category} className={`flex items-center gap-4 rounded-xl border p-4 transition-colors ${style.card}`}>
              <div className="relative shrink-0">
                {cat.status === "running" && (
                  <span className="absolute inset-0 animate-ping rounded-full bg-sky-400/40" aria-hidden />
                )}
                <span
                  className={`relative flex h-12 w-12 items-center justify-center rounded-full text-xl font-bold ${style.circle}`}
                  aria-hidden
                >
                  {glyph}
                </span>
              </div>
              <div className="min-w-0">
                <p className="text-base font-semibold text-slate-100">{LABELS[category]}</p>
                <p className={`text-sm font-medium ${style.text}`}>{statusLabel(cat.status)}</p>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
