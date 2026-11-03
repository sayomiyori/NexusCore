export type JobPageCursor = string | null;

export type JobAction =
  | { kind: "first" }
  | { kind: "next"; cursor: string }
  | { kind: "previous"; cursor: JobPageCursor };

export type JobNavigation = {
  attempted: JobAction | null;
  failed: boolean;
  history: JobPageCursor[];
  current: JobPageCursor;
};

export const MAX_HISTORY = 50;

export const initialNavigation: JobNavigation = {
  attempted: null,
  failed: false,
  history: [],
  current: null,
};

export function resetNavigation(): JobNavigation {
  return { attempted: null, failed: false, history: [], current: null };
}

export function begin(state: JobNavigation, action: JobAction): JobNavigation {
  return { ...state, attempted: action, failed: false };
}

export function succeed(state: JobNavigation): JobNavigation {
  const action = state.attempted;
  if (!action) return state;
  if (action.kind === "first")
    return { attempted: null, failed: false, history: [], current: null };
  if (action.kind === "next") {
    const history = [...state.history, state.current];
    return {
      attempted: null,
      failed: false,
      history: history.slice(Math.max(0, history.length - MAX_HISTORY)),
      current: action.cursor,
    };
  }
  return {
    attempted: null,
    failed: false,
    history: state.history.slice(0, -1),
    current: action.cursor,
  };
}

export function fail(state: JobNavigation): JobNavigation {
  return { ...state, failed: true };
}

export function canGoFirst(state: JobNavigation): boolean {
  return (
    state.current !== null ||
    (state.failed &&
      state.attempted !== null &&
      state.attempted.kind !== "first")
  );
}
