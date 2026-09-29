/**
 * Presentation-only colour themes for the three evaluation categories, shared
 * by the live-run components. Keys match the lowercase category names used
 * across the app ("functionality" | "security" | "compliance"). Nothing here
 * carries data or behaviour — it only maps a category to Tailwind classes.
 */
export interface CategoryTheme {
  icon: string;
  /** Gradient stops for `bg-gradient-to-*` (accent bars, icon tiles). */
  gradient: string;
  /** Accent text colour. */
  text: string;
  /** Border colour used when the category is actively running. */
  border: string;
  /** Soft tinted background. */
  soft: string;
  /** Coloured glow used when the category is actively running. */
  glow: string;
}

export const CATEGORY_THEME: Record<string, CategoryTheme> = {
  functionality: {
    icon: "🧩",
    gradient: "from-sky-500 to-indigo-500",
    text: "text-sky-300",
    border: "border-sky-500/50",
    soft: "bg-sky-500/10",
    glow: "shadow-sky-900/40",
  },
  security: {
    icon: "🛡️",
    gradient: "from-fuchsia-500 to-violet-500",
    text: "text-fuchsia-300",
    border: "border-fuchsia-500/50",
    soft: "bg-fuchsia-500/10",
    glow: "shadow-fuchsia-900/40",
  },
  compliance: {
    icon: "⚖️",
    gradient: "from-amber-400 to-orange-500",
    text: "text-amber-300",
    border: "border-amber-500/50",
    soft: "bg-amber-500/10",
    glow: "shadow-amber-900/40",
  },
};

export const DEFAULT_CATEGORY_THEME: CategoryTheme = {
  icon: "📊",
  gradient: "from-indigo-500 to-violet-500",
  text: "text-indigo-300",
  border: "border-indigo-500/50",
  soft: "bg-indigo-500/10",
  glow: "shadow-indigo-900/40",
};

export function themeFor(category: string): CategoryTheme {
  return CATEGORY_THEME[category.toLowerCase()] ?? DEFAULT_CATEGORY_THEME;
}
