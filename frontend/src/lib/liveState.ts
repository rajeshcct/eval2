/**
 * src/lib/liveState.ts
 *
 * Phase IV — pure reducer turning the flat list of ProgressEvents received
 * so far into the shape the Live Run View renders: per-category status +
 * round history, the Describer result (if any), and any errors seen.
 * Kept separate from the components so it's easy to reason about (and
 * re-derive from scratch on every render via useMemo) independent of React.
 */
import type { DescriberResult, FinalReport, ProgressEvent, RoundResult } from "./ws";

export const CATEGORY_ORDER = ["functionality", "security", "compliance"] as const;
export type Category = (typeof CATEGORY_ORDER)[number];

export type CategoryStatus = "pending" | "running" | "broken" | "robust_within_tested_range";

export interface CategoryLiveState {
  category: string;
  status: CategoryStatus;
  rounds: RoundResult[];
  breakingPointRound: number | null;
  /** Set once round_started fires and cleared once the matching
   * round_completed lands — lets the UI show "round N running" before the
   * scored result exists yet. */
  inProgressRound: { roundNumber: number; difficulty: number } | null;
}

export interface LiveRunState {
  describerStarted: boolean;
  describer: DescriberResult | null;
  categories: Record<string, CategoryLiveState>;
  errors: { stage: string; message: string }[];
  finalReport: FinalReport | null;
}

function emptyCategoryState(category: string): CategoryLiveState {
  return {
    category,
    status: "pending",
    rounds: [],
    breakingPointRound: null,
    inProgressRound: null,
  };
}

export function initLiveState(): LiveRunState {
  return {
    describerStarted: false,
    describer: null,
    categories: Object.fromEntries(CATEGORY_ORDER.map((c) => [c, emptyCategoryState(c)])),
    errors: [],
    finalReport: null,
  };
}

/** Rebuilds the full live-run state from every event received so far, in
 * order. Cheap enough to recompute on every new event for a run this size
 * (a handful of categories x a handful of rounds each). */
export function deriveLiveState(events: ProgressEvent[]): LiveRunState {
  const state = initLiveState();
  for (const event of events) {
    applyEvent(state, event);
  }
  return state;
}

function applyEvent(state: LiveRunState, event: ProgressEvent): void {
  switch (event.type) {
    case "describer_started":
      state.describerStarted = true;
      return;

    case "describer_completed":
      state.describer = event.data;
      return;

    case "category_started": {
      const cat = state.categories[event.data.category];
      if (cat) cat.status = "running";
      return;
    }

    case "round_started": {
      const cat = state.categories[event.data.category];
      if (cat) {
        cat.status = "running";
        cat.inProgressRound = {
          roundNumber: event.data.round_number,
          difficulty: event.data.difficulty,
        };
      }
      return;
    }

    case "round_completed": {
      const cat = state.categories[event.data.category];
      if (cat) {
        cat.rounds.push(event.data);
        cat.inProgressRound = null;
      }
      return;
    }

    case "category_completed": {
      const cat = state.categories[event.data.category];
      if (cat) {
        cat.status = event.data.status;
        cat.breakingPointRound = event.data.breaking_point;
        cat.inProgressRound = null;
        // Authoritative round list from the loop's own summary — covers
        // the (unlikely) case of a dropped round_completed frame.
        cat.rounds = event.data.rounds;
      }
      return;
    }

    case "session_completed":
      state.finalReport = event.data;
      return;

    case "error":
      state.errors.push(event.data);
      return;
  }
}
