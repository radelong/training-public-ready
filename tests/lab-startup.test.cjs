const assert = require("node:assert/strict");
const test = require("node:test");
const startup = require("../frontend/lab-startup.js");

test("startup estimate reflects one VM or a paired VM lab", () => {
  assert.equal(startup.estimateSeconds(false), 90);
  assert.equal(startup.estimateSeconds(true), 180);
});

test("startup phase uses the stable worker start timestamp, not session creation time", () => {
  assert.deepEqual(startup.startupPhase({
    state: "provisioning",
    created: 80,
    jobs: [{ action: "launch", state: "running", updated: 100 }],
  }), { phase: "provisioning", action: "launch", startedAt: 100 });
});

test("queued launch stays indeterminate until worker begins provisioning", () => {
  assert.deepEqual(startup.startupPhase({
    state: "queued",
    jobs: [{ action: "launch", state: "queued", updated: 100 }],
  }), { phase: "queued", action: "launch" });
});

test("reset and retry phases keep their action for accurate status copy", () => {
  assert.deepEqual(startup.startupPhase({ state: "resetting", jobs: [
    { action: "reset", state: "running", updated: 100 },
  ] }), { phase: "provisioning", action: "reset", startedAt: 100 });
  assert.deepEqual(startup.startupPhase({ state: "queued", jobs: [
    { action: "retry", state: "queued" },
  ] }), { phase: "queued", action: "retry" });
});

test("missing timing data stays indeterminate instead of using an old session timestamp", () => {
  const phase = startup.startupPhase({ state: "provisioning", created: 10, jobs: [] });
  assert.deepEqual(phase, { phase: "provisioning", action: "launch" });
  const result = startup.progress({ ...phase, estimate: 90, now: 1000 });
  assert.equal(result.indeterminate, true);
  assert.equal(result.percent, null);
  assert.match(result.status, /time estimate will appear/i);
});

test("exercise actions do not show VM startup progress", () => {
  assert.equal(startup.startupPhase({
    state: "ready",
    jobs: [{ action: "start", state: "running", updated: 100 }],
  }), null);
});

test("ready and failed sessions do not show a startup indicator", () => {
  assert.equal(startup.startupPhase({ state: "ready", jobs: [] }), null);
  assert.equal(startup.startupPhase({ state: "error", jobs: [] }), null);
});

test("queued status does not pretend a countdown or measured percentage exists", () => {
  const result = startup.progress({ phase: "queued", estimate: 90, now: 120 });
  assert.equal(result.indeterminate, true);
  assert.equal(result.percent, null);
  assert.match(result.status, /estimate begins when setup starts/i);
});

test("estimated bar advances but remains below completion until backend readiness", () => {
  const result = startup.progress({ phase: "provisioning", startedAt: 100, estimate: 90, now: 145 });
  assert.equal(result.percent, 48);
  assert.match(result.status, /Best guess/);
  assert.ok(result.percent < 100);
});

test("slow startup holds below completion and avoids a false zero-time estimate", () => {
  const result = startup.progress({ phase: "provisioning", startedAt: 100, estimate: 90, now: 280 });
  assert.equal(result.percent, 92);
  assert.match(result.status, /Taking longer than usual/);
  assert.ok(!/0 seconds|0 minutes/.test(result.status));
});

test("estimate text rounds time rather than showing a seconds countdown", () => {
  const result = startup.progress({ phase: "provisioning", startedAt: 100, estimate: 90, now: 130 });
  assert.match(result.status, /about 1 minute remaining/);
  assert.ok(!/\d+ seconds remaining/.test(result.status));
});

test("paired startup estimate uses singular grammar for one minute", () => {
  const result = startup.progress({ phase: "provisioning", startedAt: 100, estimate: 180, now: 220 });
  assert.match(result.status, /about 1 minute remaining/);
});

test("typical duration label stays derived from the VM-count estimate", () => {
  assert.equal(startup.estimateLabel(false), "Typical setup: about 1 minute 30 seconds for a single-VM lab.");
  assert.equal(startup.estimateLabel(true), "Typical setup: about 3 minutes for a paired-VM lab.");
});
