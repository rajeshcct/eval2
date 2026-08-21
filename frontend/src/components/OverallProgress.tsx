import { CATEGORY_ORDER, type CategoryLiveState } from "../lib/liveState";

interface OverallProgressProps {
  categories: Record<string, CategoryLiveState>;
}

const LABELS: Record<string, string> = {
  functionality: "Functionality",
  security: "Security",
  compliance: "Compliance",
};

function stepStyle(status: CategoryLiveState["status"]): { dot: string; text: string } {
  switch (status) {
    case "pending":
      return { dot: "bg-slate-700", text: "text-slate-500" };
    case "running":
      return { dot: "bg-blue-500 animate-pulse", text: "text-blue-300" };
    case "broken":
      return { dot: "bg-red-500", text: "text-red-300" };
    case "robust_within_tested_range":
      return { dot: "bg-emerald-500", text: "text-emerald-300" };
  }
}

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

/**
 * Phase IV requirement 3 — an overall progress indicator showing which of
 * the 3 categories are done / running / pending.
 */
export default function OverallProgress({ categories }: OverallProgressProps) {
  return (
    <div className="flex items-center gap-6 rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3">
      {CATEGORY_ORDER.map((category, i) => {
        const cat = categories[category];
        const style = stepStyle(cat.status);
        return (
          <div key={category} className="flex items-center gap-2">
            {i > 0 && <span className="mr-4 h-px w-6 bg-slate-700" aria-hidden />}
            <span className={`h-2.5 w-2.5 rounded-full ${style.dot}`} aria-hidden />
            <span className="text-sm font-medium text-slate-200">{LABELS[category]}</span>
            <span className={`text-xs ${style.text}`}>{statusLabel(cat.status)}</span>
          </div>
        );
      })}
    </div>
  );
}
