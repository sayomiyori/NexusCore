import assert from "node:assert/strict";
import { test } from "node:test";
import {
  type BotAction,
  type BotNavigation,
  begin,
  canGoFirst,
  canGoPrevious,
  canRetry,
  cursorFor,
  fail,
  initialNavigation,
  MAX_HISTORY,
  previousCursor,
  resetNavigation,
  succeed,
} from "../lib/bot-history.ts";

const first: BotAction = { kind: "first" };
const next = (cursor: string): BotAction => ({ kind: "next", cursor });
const previous = (cursor: string | null): BotAction => ({
  kind: "previous",
  cursor,
});

const at = (...actions: BotAction[]): BotNavigation =>
  actions.reduce(
    (state, action) => succeed(begin(state, action)),
    initialNavigation,
  );

test("first page success clears history and current cursor", () => {
  const stale = fail(begin(at(next("b")), next("c")));
  const done = succeed(begin(stale, first));
  assert.deepEqual(done, {
    attempted: null,
    failed: false,
    history: [],
    current: null,
  });
  assert.equal(canGoFirst(done), false);
  assert.equal(canGoPrevious(done), false);
  assert.equal(canRetry(done), false);
});

test("next pushes the left page and previous pops across three pages", () => {
  let state = at(next("c1"));
  assert.deepEqual(state.history, [null]);
  assert.equal(state.current, "c1");
  assert.equal(previousCursor(state), null);
  assert.equal(canGoFirst(state), true);
  assert.equal(canGoPrevious(state), true);

  state = at(next("c1"), next("c2"));
  assert.deepEqual(state.history, [null, "c1"]);
  assert.equal(state.current, "c2");
  assert.equal(previousCursor(state), "c1");

  state = at(next("c1"), next("c2"), previous("c1"));
  assert.deepEqual(state.history, [null]);
  assert.equal(state.current, "c1");

  state = at(next("c1"), next("c2"), previous("c1"), previous(null));
  assert.deepEqual(state.history, []);
  assert.equal(state.current, null);
  assert.equal(canGoPrevious(state), false);
  assert.equal(canGoFirst(state), false);
});

test("a failed bot page keeps the successful position and offers previous, retry and first", () => {
  const second = at(next("c1"), next("c2"));
  const failed = fail(begin(second, next("c3")));
  assert.deepEqual(failed.history, second.history);
  assert.equal(failed.current, "c2");
  assert.equal(failed.failed, true);
  assert.equal(canRetry(failed), true);
  assert.deepEqual(failed.attempted, next("c3"));
  assert.equal(canGoPrevious(failed), true);
  assert.equal(canGoFirst(failed), true);

  const retried = succeed(failed);
  assert.deepEqual(retried.history, [null, "c1", "c2"]);
  assert.equal(retried.current, "c3");
});

test("a failed previous keeps the history entry and does not double-pop", () => {
  const third = at(next("c1"), next("c2"));
  const failed = fail(begin(third, previous("c1")));
  assert.deepEqual(failed.history, [null, "c1"]);
  assert.equal(failed.current, "c2");
  assert.equal(previousCursor(failed), "c1");
  assert.equal(canGoPrevious(failed), true);

  const retried = succeed(failed);
  assert.deepEqual(retried.history, [null]);
  assert.equal(retried.current, "c1");
});

test("a failed first attempt does not offer first again", () => {
  const failed = fail(begin(initialNavigation, first));
  assert.equal(canGoFirst(failed), false);
  assert.equal(canGoPrevious(failed), false);
  assert.equal(canRetry(failed), true);

  const onSecondPage = at(next("c1"), next("c2"));
  const failedFirst = fail(begin(onSecondPage, first));
  assert.equal(
    canGoFirst(failedFirst),
    true,
    "a failed First from a later page must still allow First",
  );
  assert.equal(canGoPrevious(failedFirst), true);
});

test("history is capped at 50 entries dropping the oldest", () => {
  let state = initialNavigation;
  for (let index = 0; index < MAX_HISTORY + 5; index += 1)
    state = succeed(begin(state, next(`c${index}`)));
  assert.equal(state.history.length, MAX_HISTORY);
  assert.equal(state.history[0], "c4");
  assert.equal(state.history.at(-1), `c${MAX_HISTORY + 3}`);
  assert.equal(state.current, `c${MAX_HISTORY + 4}`);
});

test("cursorFor maps every action to the cursor it reads", () => {
  assert.equal(cursorFor(first), null);
  assert.equal(cursorFor(next("c1")), "c1");
  assert.equal(cursorFor(previous(null)), null);
  assert.equal(cursorFor(previous("c1")), "c1");
});

test("transitions never mutate the source state or its history array", () => {
  const source = at(next("c1"));
  const before = structuredClone(source);
  begin(source, next("c2"));
  fail(source);
  succeed(source);
  resetNavigation();
  assert.deepEqual(source, before);
  assert.notEqual(resetNavigation().history, initialNavigation.history);
});
