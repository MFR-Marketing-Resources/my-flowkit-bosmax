"use strict";

// Regression tests for the adaptive F2V mode-selection decision
// (_modeStepConfirmDecision) — reproduces the live failure where Google Flow
// exposed no standalone "Video" option (ERR_F2V_OPTION_VIDEO_NOT_FOUND) and
// the candidates were global nav (Flow TV / Help / banners / New project).
// Pure logic — no live Flow tab required.

const assert = (cond, msg) => {
  if (!cond) throw new Error(`ASSERTION_FAILED: ${msg}`);
};

const runner = require("../extension/f2v-flow-queue-runner.js");
const decide = runner._modeStepConfirmDecision;
assert(typeof decide === "function", "_modeStepConfirmDecision must be exported");

// 1. Current-failure fixture INVERTED: no "Video" option but a valid live F2V
//    composer (Nano Banana pill bearing ratio/count) -> accept / skip mode click.
let d = decide(
  "mode",
  { ok: true, detectedRatio: "9:16", detectedCount: "1x", pillText: "Nano Banana Pro crop_9_16 1x" },
  [{ role: "option", text: "Veo 3.1 - Lite" }],
);
assert(d.accept === true, "live composer -> skip missing Video click");
assert(d.reason === "F2V_COMPOSER_ALREADY_READY_NO_MODE_TAB", `reason was ${d.reason}`);

// 2. Exact live failure: global nav candidates (TV/Help/banners/New project),
//    no composer pill -> must NOT treat nav as mode options; fail closed clearly.
d = decide(
  "mode",
  { ok: true, topMode: "UNKNOWN", subMode: "UNKNOWN", pillText: "unknown" },
  [
    { role: "a", text: "tvFlow TV" },
    { role: "button", text: "help_outlinedFlow Help Center" },
    { role: "i", text: "more_vert" },
    { role: "button", text: "Go to banner 1" },
    { role: "button", text: "add_2New project" },
  ],
);
assert(d.accept === false, "landing nav must not be accepted as a mode choice");
assert(d.reason === "NOT_IN_F2V_COMPOSER_SURFACE_LANDING_NAV_ONLY", `reason was ${d.reason}`);

// 3. Real missing composer: no tokens, no nav -> fail closed.
d = decide("mode", { ok: true, pillText: "" }, []);
assert(d.accept === false, "missing composer -> fail closed");
assert(d.reason === "F2V_COMPOSER_SURFACE_NOT_DETECTED", `reason was ${d.reason}`);

// 4. Submode (Frames) with a live composer -> accept / skip.
d = decide("submode", { ok: true, detectedCount: "1x" }, []);
assert(d.accept === true, "submode live composer -> skip missing Frames click");

// 5. Non-mode step (ratio) is not handled by this decision (frozen path untouched).
d = decide("ratio", { ok: true, detectedRatio: "9:16" }, []);
assert(d.accept === false && d.reason === "NOT_A_MODE_STEP", "ratio is not a mode step");

// 6. composerLive requires failState.ok === true (a stale/errored probe never accepts).
d = decide("mode", { ok: false, detectedRatio: "9:16" }, []);
assert(d.accept === false, "errored composer probe must not accept");

console.log("PASS test-f2v-mode-adaptive: all 6 cases");
