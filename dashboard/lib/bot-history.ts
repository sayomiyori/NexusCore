export type BotPageCursor = string | null;

export type BotAction =
  | { kind: "first" }
  | { kind: "next"; cursor: string }
  | { kind: "previous"; cursor: BotPageCursor };

export type BotNavigation = {
  attempted: BotAction | null;
  failed: boolean;
  history: BotPageCursor[];
  current: BotPageCursor;
};

export const MAX_HISTORY = 50;

export const initialNavigation: BotNavigation = {
  attempted: null,
  failed: false,
  history: [],
  current: null,
};

export function resetNavigation(): BotNavigation {
  return { attempted: null, failed: false, history: [], current: null };
}

export function begin(state: BotNavigation, action: BotAction): BotNavigation {
  return { ...state, attempted: action, failed: false };
}

export function succeed(state: BotNavigation): BotNavigation {
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

export function fail(state: BotNavigation): BotNavigation {
  return { ...state, failed: true };
}

export function cursorFor(action: BotAction): BotPageCursor {
  return action.kind === "first" ? null : action.cursor;
}

export function canGoFirst(state: BotNavigation): boolean {
  return (
    state.current !== null ||
    (state.failed &&
      state.attempted !== null &&
      state.attempted.kind !== "first")
  );
}

export function canGoPrevious(state: BotNavigation): boolean {
  return state.history.length > 0;
}

export function previousCursor(state: BotNavigation): BotPageCursor {
  return state.history.at(-1) ?? null;
}

export function canRetry(state: BotNavigation): boolean {
  return state.failed && state.attempted !== null;
}
