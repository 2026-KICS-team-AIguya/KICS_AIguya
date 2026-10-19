const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const context = vm.createContext({ Date, Math, Map });
vm.runInContext(fs.readFileSync(path.join(__dirname, "../web/kiosk-measured.js"), "utf8"), context);
const start = Date.UTC(2026, 9, 19, 3);
function data(level, now = start, changes = {}) {
  context.reading = { status: "ok", input_kind: "sensor", level, timestamp: now - 5000, ...changes };
  context.now = now;
  return vm.runInContext("measuredKioskData(reading, now)", context);
}
const reset = () => vm.runInContext("measuredKioskFlow = null", context);
const initial = ["여유", "보통", "혼잡"].map(level => { reset(); return data(level); });
assert.ok(initial[0].staying_estimation.current_eating < initial[1].staying_estimation.current_eating);
assert.ok(initial[1].staying_estimation.current_eating < initial[2].staying_estimation.current_eating);
for (const changes of [{ status: "stale" }, { status: "calibrating" }, { input_kind: "synthetic" },
  { input_kind: "replay" }, { level: "unknown" }, { timestamp: start - 40000 }, { timestamp: null }]) {
  assert.equal(data("보통", start, changes), null);
}
reset();
let previous = data("여유");
const first = previous;
for (let step = 1; step <= 600; step++) {
  const now = start + step * 10000;
  const level = step < 120 ? "여유" : step < 360 ? "혼잡" : "보통";
  const current = data(level, now);
  const s = current.staying_estimation, p = previous.staying_estimation;
  assert.ok(0 <= s.leaving_in_10m && s.leaving_in_10m <= s.current_eating && s.current_eating <= 120);
  assert.ok(Math.abs(s.current_eating - p.current_eating) <= 1);
  assert.ok(Math.abs(current.surge_momentum.recent_5m - previous.surge_momentum.recent_5m) <= 1);
  assert.equal(s.total_5m_trend[5], current.surge_momentum.recent_5m);
  if (step === 30) assert.deepEqual(Array.from(s.total_5m_trend).slice(0, 5), Array.from(first.staying_estimation.total_5m_trend).slice(1));
  const repeat = data(level, now + 1000);
  assert.deepEqual(JSON.parse(JSON.stringify(s)), JSON.parse(JSON.stringify(repeat.staying_estimation)));
  assert.deepEqual(JSON.parse(JSON.stringify(current.surge_momentum)), JSON.parse(JSON.stringify(repeat.surge_momentum)));
  previous = current;
}
console.log("PASS: CSI grade conditioning, continuous history, bounded counts, stale/synthetic input rejection.");
