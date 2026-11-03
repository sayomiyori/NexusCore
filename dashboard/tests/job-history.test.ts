import assert from "node:assert/strict";
import { test } from "node:test";
import {
  begin,
  canGoFirst,
  fail,
  initialNavigation,
  MAX_HISTORY,
  resetNavigation,
  succeed,
} from "../lib/job-history.ts";

const canGoPrevious = (state: typeof initialNavigation) =>
  state.history.length > 0;
const previousCursor = (state: typeof initialNavigation) =>
  state.history.at(-1) ?? null;
const canRetry = (state: typeof initialNavigation) =>
  state.failed && state.attempted !== null;

const first = { kind: "first" } as const;
const next = (cursor: string) => ({ kind: "next", cursor }) as const;
const previous = (cursor: string | null) =>
  ({ kind: "previous", cursor }) as const;

test("first page success clears history and current cursor", () => {
  const attempted = begin(
    { ...initialNavigation, history: ["a"], current: "a" },
    next("b"),
  );
  const failed = fail(attempted);
  const done = succeed(begin(failed, first));
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
  let state = succeed(begin(initialNavigation, next("c1")));
  assert.deepEqual(state.history, [null]);
  assert.equal(state.current, "c1");
  assert.equal(previousCursor(state), null);
  assert.equal(canGoFirst(state), true);
  assert.equal(canGoPrevious(state), true);

  state = succeed(begin(state, next("c2")));
  assert.deepEqual(state.history, [null, "c1"]);
  assert.equal(state.current, "c2");
  assert.equal(previousCursor(state), "c1");

  state = succeed(begin(state, previous("c1")));
  assert.deepEqual(state.history, [null]);
  assert.equal(state.current, "c1");

  state = succeed(begin(state, previous(null)));
  assert.deepEqual(state.history, []);
  assert.equal(state.current, null);
  assert.equal(canGoPrevious(state), false);
  assert.equal(canGoFirst(state), false);
});

test("a failed attempt keeps the successful page and offers previous, retry and first", () => {
  const atSecond = succeed(
    begin(succeed(begin(initialNavigation, next("c1"))), next("c2")),
  );
  const failed = fail(begin(atSecond, next("c3")));
  assert.deepEqual(failed.history, atSecond.history);
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

test("a failed first attempt does not offer first again", () => {
  const failed = fail(begin(initialNavigation, first));
  assert.equal(canGoFirst(failed), false);
  assert.equal(canGoPrevious(failed), false);
  assert.equal(canRetry(failed), true);

  const onSecondPage = succeed(
    begin(succeed(begin(initialNavigation, next("c1"))), next("c2")),
  );
  const failedFirst = fail(begin(onSecondPage, first));
  assert.equal(
    canGoFirst(failedFirst),
    true,
    "a failed First from a later page must still allow First",
  );
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

test("transitions never mutate the source state or its history array", () => {
  const source = succeed(begin(initialNavigation, next("c1")));
  const before = structuredClone(source);
  begin(source, next("c2"));
  fail(source);
  succeed(source);
  resetNavigation();
  assert.deepEqual(source, before);
  assert.notEqual(resetNavigation().history, initialNavigation.history);
});
