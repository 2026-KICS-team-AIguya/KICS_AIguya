"use strict";

const KIOSK_WINDOW_MS = 5 * 60 * 1000;
const KIOSK_SAMPLE_MS = 5000;

// Counts represent newly issued tickets, not a cumulative counter or people.
function createKioskDemo(config, now) {
  if (!config) return null;
  const readings = [];
  const samples = KIOSK_WINDOW_MS / KIOSK_SAMPLE_MS;
  for (const [windowIndex, total] of [config.previous, config.recent].entries()) {
    for (let index = 0; index < samples; index++) {
      readings.push({
        timestamp: now - (2 - windowIndex) * KIOSK_WINDOW_MS + (index + .5) * KIOSK_SAMPLE_MS,
        count: Math.floor((index + 1) * total / samples) - Math.floor(index * total / samples),
      });
    }
  }
  return { scope: config.scope, available: true, startedAt: now, tick: 0, pattern: [...config.pattern], readings };
}

function advanceKioskDemo(kiosk, now) {
  if (!kiosk || now < kiosk.startedAt) return;
  const tick = Math.floor((now - kiosk.startedAt) / KIOSK_SAMPLE_MS);
  // Limit demo backfill after a long pause to the two windows we display.
  const firstTick = Math.max(kiosk.tick + 1, tick - 119);
  for (let index = firstTick; index <= tick; index++) {
    kiosk.readings.push({
      timestamp: kiosk.startedAt + (index - .5) * KIOSK_SAMPLE_MS,
      count: kiosk.pattern[(index - 1) % kiosk.pattern.length],
    });
  }
  kiosk.tick = Math.max(kiosk.tick, tick);
  kiosk.readings = kiosk.readings.filter(reading => reading.timestamp >= now - 2 * KIOSK_WINDOW_MS);
}

function getKioskSummary(kiosk, now) {
  if (!kiosk?.available || !Array.isArray(kiosk.readings) || !Number.isFinite(now)) return null;
  const recentStart = now - KIOSK_WINDOW_MS;
  const previousStart = recentStart - KIOSK_WINDOW_MS;
  let recent = 0, previous = 0;
  for (const reading of kiosk.readings) {
    if (!Number.isFinite(reading.timestamp) || !Number.isInteger(reading.count) || reading.count < 0) return null;
    if (reading.timestamp >= recentStart && reading.timestamp < now) recent += reading.count;
    else if (reading.timestamp >= previousStart && reading.timestamp < recentStart) previous += reading.count;
  }
  const change = recent - previous;
  return { scope: kiosk.scope, recent, previous, change, percent: previous > 0 ? Math.round(change / previous * 100) : null };
}
