"use strict";

const congestionApiBase = window.CONGESTION_API_BASE || (window.location.pathname.startsWith("/dashboard") ? window.location.origin : null);
const CONGESTION_LEVELS = { "여유": "free", "보통": "moderate", "혼잡": "busy" };
const MEASUREMENT_LABELS = {
  waiting: "측정 대기", calibrating: "측정 준비 중", skipped: "확인 중",
  stale: "업데이트 지연", unconnected: "혼잡도 준비 중", unavailable: "혼잡도 준비 중",
  offline: "연결 확인 중", unconfigured: "혼잡도 준비 중", loading: "확인 중",
};
let congestionController;
let congestionRequest = 0;

function applyCongestionSnapshot(payload, locationId) {
  if (payload.version !== 2 || payload.location_id !== locationId || !Array.isArray(payload.floors) || !payload.kiosk) {
    throw new Error("혼잡도 API 응답 형식이 다릅니다.");
  }
  for (const floor of payload.floors) {
    if (!Number.isInteger(floor.floor) || !["waiting", "calibrating", "ok", "skipped", "stale", "unconnected", "unavailable"].includes(floor.status) ||
        (floor.history !== undefined && !Array.isArray(floor.history))) throw new Error("잘못된 층별 측정 상태입니다.");
    if (floor.status === "ok" && (!Object.hasOwn(CONGESTION_LEVELS, floor.level) || !Number.isFinite(floor.confidence) || floor.confidence < 0 || floor.confidence > 1)) {
      throw new Error("잘못된 AI 추론 결과입니다.");
    }
  }
  if (!["waiting", "collecting", "ok", "stale"].includes(payload.kiosk.status)) throw new Error("잘못된 발권 수신 상태입니다.");
  state.snapshots[locationId] = payload;
  state.connection[locationId] = "connected";
  state.lastUpdated = new Date();
}

async function refreshCongestion() {
  const locationId = state.locationId;
  if (!congestionApiBase) {
    state.connection[locationId] = "unconfigured";
    return;
  }
  const request = ++congestionRequest;
  congestionController?.abort();
  const controller = new AbortController();
  congestionController = controller;
  const timer = setTimeout(() => controller.abort(), 8000);
  state.refreshing = true;
  try {
    const response = await fetch(`${congestionApiBase.replace(/\/$/, "")}/congestion?location_id=${encodeURIComponent(locationId)}`, {
      signal: controller.signal, cache: "no-store",
    });
    if (!response.ok) throw new Error("혼잡도 서버 연결 실패");
    const payload = await response.json();
    if (request === congestionRequest) applyCongestionSnapshot(payload, locationId);
  } catch {
    if (request === congestionRequest) state.connection[locationId] = "offline";
  } finally {
    clearTimeout(timer);
    if (request === congestionRequest) state.refreshing = false;
  }
}

function floorReading(floor) {
  const location = activeLocation();
  const snapshot = state.snapshots[location.id];
  const reading = snapshot?.floors.find(item => item.floor === floor.id);
  const scope = snapshot?.sensor_scope;
  const connectedFloor = scope?.location_id === location.id && scope.floor === floor.id;
  if (floor.demo && !connectedFloor) return { ...floor.demo, status: "ok", mode: "demo", history: floor.history };
  if (state.connection[location.id] !== "connected") {
    return { status: state.connection[location.id] || "loading", level: null, input_kind: reading?.input_kind, history: [] };
  }
  return reading || { status: "unconnected", level: null, history: [] };
}

function measurementStyle(reading) {
  if (reading.status === "ok" && Object.hasOwn(CONGESTION_LEVELS, reading.level)) {
    return { name: reading.level, className: CONGESTION_LEVELS[reading.level] };
  }
  return { name: MEASUREMENT_LABELS[reading.status] || "확인 필요", className: "unknown" };
}

function measurementSource(reading) {
  if (reading.mode === "demo" || reading.input_kind === "synthetic") return "예시 데이터";
  if (reading.input_kind === "replay") return "기록 데이터";
  return "실시간 혼잡도";
}
