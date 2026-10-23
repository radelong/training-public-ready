(function (root, factory) {
  const startup = factory();
  if (typeof module === "object" && module.exports) module.exports = startup;
  else root.AcademyLabStartup = startup;
})(globalThis, function () {
  "use strict";

  function estimateSeconds(paired) {
    return paired ? 180 : 90;
  }

  function startupPhase(session) {
    if (!session || ["ready", "error", "ending", "ended"].includes(session.state)) return null;
    const job = (session.jobs || []).find(item =>
      ["launch", "reset", "retry"].includes(item.action) && ["queued", "running"].includes(item.state)
    );
    if (job?.state === "queued" || (!job && session.state === "queued")) {
      return { phase: "queued", action: job?.action || "launch" };
    }
    if (job?.state === "running") {
      return { phase: "provisioning", action: job.action, startedAt: Number(job.updated) };
    }
    if (["provisioning", "resetting"].includes(session.state)) {
      return { phase: "provisioning", action: session.state === "resetting" ? "reset" : "launch" };
    }
    return null;
  }

  function remainingText(seconds) {
    const rounded = Math.ceil(Math.max(0, seconds) / 30) * 30;
    if (rounded < 30) return "less than 30 seconds";
    if (rounded < 60) return "about 30 seconds";
    if (rounded < 90) return "about 1 minute";
    const minutes = Math.floor(rounded / 60);
    const remainder = rounded % 60;
    const minuteLabel = `${minutes} minute${minutes === 1 ? "" : "s"}`;
    return remainder ? `about ${minuteLabel} ${remainder} seconds` : `about ${minuteLabel}`;
  }

  function progress({ phase, startedAt, estimate, now = Date.now() / 1000 }) {
    if (phase === "queued") {
      const status = "Waiting for a provisioning slot. The time estimate begins when setup starts.";
      return { indeterminate: true, percent: null, status, ariaValueText: status };
    }

    const expected = Math.max(30, Number(estimate) || 90);
    const start = Number(startedAt);
    if (!Number.isFinite(start)) {
      const status = "Setup is underway. A time estimate will appear when timing data is available.";
      return { indeterminate: true, percent: null, status, ariaValueText: status };
    }
    const elapsed = Number.isFinite(start) ? Math.max(0, now - start) : 0;
    const fraction = elapsed / expected;
    const percent = Math.min(92, Math.round(8 + Math.min(fraction, 1) * 80 + Math.min(Math.max(fraction - 1, 0), 1) * 4));
    const status = elapsed >= expected
      ? "Taking longer than usual. Your lab is still preparing."
      : `Best guess: ${remainingText(expected - elapsed)} remaining.`;
    return { indeterminate: false, percent, status, ariaValueText: `Estimated progress. ${status}` };
  }

  function estimateLabel(paired) {
    const type = paired ? "paired-VM lab" : "single-VM lab";
    return `Typical setup: ${remainingText(estimateSeconds(paired))} for a ${type}.`;
  }

  return { estimateSeconds, estimateLabel, progress, startupPhase };
});
