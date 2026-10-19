"use strict";

// CSI grades condition a virtual ticket stream; none of these counts are measured.
let measuredKioskFlow = null;
const KIOSK_TICK_MS = 10000;
const KIOSK_DEMAND = { "여유": .2, "보통": .55, "혼잡": .85 };

function measuredTicket(tick, level) {
  // Stable for each time slot, so revisiting a mode cannot reroll its history.
  let hash = Math.imul(tick ^ 0x9e3779b9, 0x85ebca6b);
  hash = Math.imul(hash ^ (hash >>> 13), 0xc2b2ae35);
  const draw = ((hash ^ (hash >>> 16)) >>> 0) / 4294967296;
  return Number(draw < KIOSK_DEMAND[level] + .04 * Math.sin(tick / 180));
}

function measuredKioskData(reading, now = Date.now()) {
  const age = now - reading.timestamp;
  if (reading.status !== "ok" || reading.input_kind !== "sensor" ||
      !Object.hasOwn(KIOSK_DEMAND, reading.level) || !Number.isFinite(reading.timestamp) || age > 35000 || age < -10000) return null;
  const tick = Math.floor(now / KIOSK_TICK_MS);
  let flow = measuredKioskFlow;
  if (!flow || tick < flow.tick || tick - flow.tick > 3 || reading.timestamp < flow.timestamp) {
    // Initial history is a mock warm start conditioned on the current grade.
    flow = { tick: tick - 180, level: reading.level, timestamp: reading.timestamp, tickets: new Map() };
  }
  const changedAt = Math.floor(reading.timestamp / KIOSK_TICK_MS);
  for (let t = flow.tick; t < tick; t++) {
    flow.tickets.set(t, measuredTicket(t, t < changedAt ? flow.level : reading.level));
  }
  flow.tick = tick;
  flow.level = reading.level;
  flow.timestamp = reading.timestamp;
  for (const t of flow.tickets.keys()) if (t < tick - 180) flow.tickets.delete(t);
  measuredKioskFlow = flow;
  const sum = (start, end) => {
    let total = 0;
    for (let t = start; t < end; t++) total += flow.tickets.get(t) || 0;
    return total;
  };
  const trend = Array.from({ length: 6 }, (_, i) => sum(tick - (6 - i) * 30, tick - (5 - i) * 30));
  const recent = trend[5], previous = trend[4];
  const surge = previous ? Math.round((recent - previous) / previous * 1000) / 10 : recent ? null : 0;
  return {
    version: 1, data_source: "mock", location_id: "sangnok", floor: 1, mode: "measured",
    as_of: new Date(now).toISOString(), operating: true,
    summary_briefing: `1층 센서 혼잡도는 ‘${reading.level}’예요. 이 등급을 기준으로 가상 발권 흐름을 구성하고 있어요.`,
    staying_estimation: { current_eating: sum(tick - 123, tick - 3), leaving_in_10m: sum(tick - 123, tick - 63), total_5m_trend: trend },
    surge_momentum: { recent_5m: recent, prev_5m: previous, surge_rate_percent: surge, is_surging: surge !== null && surge >= 25 },
    golden_time_stats: { diff_vs_usual_percent: Math.round((recent + previous - 40) / 40 * 1000) / 10,
      recommended_time: null, tip: "실제 발권량·인원 측정값이 아닌 CSI 혼잡도 기반 목데이터예요." },
  };
}
