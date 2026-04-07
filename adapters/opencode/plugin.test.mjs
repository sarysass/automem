import test from "node:test";
import assert from "node:assert/strict";

const { __test } = await import("./dist/automem.plugin.js");

test("beginUserTurn clears stale assistant state for the next capture cycle", () => {
  const next = __test.beginUserTurn(
    {
      latestUserMessage: "旧问题",
      latestAssistantMessage: "旧回答",
      latestRecallContext: "旧 recall",
      lastCapturedFingerprint: "fingerprint",
    },
    "新问题",
  );

  assert.equal(next.latestUserMessage, "新问题");
  assert.equal(next.latestAssistantMessage, undefined);
  assert.equal(next.latestRecallContext, undefined);
  assert.equal(next.lastCapturedFingerprint, "fingerprint");
});

test("shouldAutoCapture filters trivial and system-noise turns", () => {
  assert.equal(__test.shouldAutoCapture("试一下", "收到"), false);
  assert.equal(
    __test.shouldAutoCapture(
      "<system-reminder> [ALL BACKGROUND TASKS COMPLETE]",
      "Completed: bg_job",
    ),
    false,
  );
  assert.equal(
    __test.shouldAutoCapture(
      "现在再来解决 skills 用不了的问题，看看这个要怎么改",
      "我先把相关调用链梳理一下，再给你一个具体修法。",
    ),
    true,
  );
});
