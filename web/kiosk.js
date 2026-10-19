"use strict";

const kioskModes = [
  { label: "랜덤", id: "kiosk-mode-random" },
  { label: "실측 기반", id: "kiosk-mode-measured" },
];
const kioskState = { mode: 0, payload: null, status: "loading", request: 0, controller: null };
const kioskEndpoint = window.KIOSK_API_URL || (window.location.pathname.startsWith("/dashboard")
  ? `${window.location.origin}/kiosk/comprehensive-analysis`
  : window.location.protocol === "file:" ? null : `${window.location.origin}/api/kiosk-analysis`);

function validKiosk(data) {
  const finite = x => typeof x === "number" && Number.isFinite(x);
  const count = x => Number.isInteger(x) && x >= 0;
  const optional = x => x === null || finite(x);
  const s = data?.staying_estimation, m = data?.surge_momentum, g = data?.golden_time_stats;
  return data?.version === 1 && data.data_source === "mock" && data.location_id === "sangnok" && data.floor === 1 &&
    typeof data.summary_briefing === "string" && typeof data.operating === "boolean" && Number.isFinite(Date.parse(data.as_of)) &&
    s && count(s.current_eating) && s.current_eating <= 120 && count(s.leaving_in_10m) && s.leaving_in_10m <= s.current_eating &&
    Array.isArray(s.total_5m_trend) && s.total_5m_trend.length === 6 && s.total_5m_trend.every(count) &&
    m && optional(m.surge_rate_percent) && typeof m.is_surging === "boolean" && count(m.recent_5m) && count(m.prev_5m) &&
    g && optional(g.diff_vs_usual_percent) && (g.recommended_time === null || typeof g.recommended_time === "string") && typeof g.tip === "string";
}

async function refreshKiosk() {
  const request = ++kioskState.request;
  kioskState.controller?.abort();
  if (state.locationId !== "sangnok" || state.floorId !== 1) { renderKiosk(); return; }
  const reading = floorReading(activeLocation().floors.find(f => f.id === 1));
  const measured = measuredKioskData(reading);
  if (kioskState.mode === 1) {
    kioskState.payload = measured;
    kioskState.status = measured ? "ready" : "waiting";
    renderKiosk();
    return;
  }
  if (!kioskEndpoint) { kioskState.status = "unconfigured"; renderKiosk(); return; }
  const controller = new AbortController();
  kioskState.controller = controller;
  const timeout = setTimeout(() => controller.abort(), 8000);
  if (!kioskState.payload) kioskState.status = "loading";
  renderKiosk();
  try {
    const response = await fetch(kioskEndpoint, { signal: controller.signal, cache: "no-store" });
    if (!response.ok) throw new Error("kiosk unavailable");
    const data = await response.json();
    if (!validKiosk(data)) throw new Error("invalid kiosk response");
    if (request === kioskState.request) { kioskState.payload = data; kioskState.status = "ready"; }
  } catch {
    if (request === kioskState.request) kioskState.status = "error";
  } finally {
    clearTimeout(timeout);
    if (request === kioskState.request) renderKiosk();
  }
}

function kioskSigned(value) { return `${value > 0 ? "+" : ""}${value}%`; }

function renderKiosk() {
  const visible = state.locationId === "sangnok";
  const available = visible && state.floorId === 1;
  $("kiosk-service").hidden = !visible;
  $("kiosk-mode").hidden = !available;
  $("kiosk-active-content").hidden = !available;
  $("kiosk-source-badge").hidden = !available;
  $("kiosk-pending").hidden = !visible || available;
  if (!visible) return;
  $("kiosk-floor-caption").textContent = `상록원 ${state.floorId}층 · 키오스크 안내`;
  $("kiosk-title").textContent = available ? "지금, 식당은 어떤가요?" : "키오스크 안내";
  if (!available) {
    $("kiosk-pending-message").textContent = `${state.floorId}층 키오스크 정보는 준비 중입니다.`;
    return;
  }
  kioskModes.forEach((mode, index) => $(mode.id).setAttribute("aria-pressed", String(index === kioskState.mode)));
  const measuredMode = kioskState.mode === 1;
  $("kiosk-source-badge").textContent = measuredMode ? "CSI 기반 가상 데이터" : "랜덤 가상 데이터";
  $("kiosk-mode-note").textContent = measuredMode ? "측정된 혼잡도를 따라가는 목데이터 · 실제 발권량과 다릅니다" : "발권 흐름을 유지하며 10초마다 갱신되는 목데이터입니다";
  const data = kioskState.payload;
  const ready = kioskState.status === "ready" && data;
  $("kiosk-results").hidden = !ready;
  $("kiosk-retry").hidden = !["error", "unconfigured"].includes(kioskState.status);
  $("kiosk-asof").textContent = ready ? `${timeFormat.format(new Date(data.as_of))} 기준 · ${measuredMode ? "실측 기반 목데이터" : "랜덤 목데이터"}` : "상록원 1층 · 발권 현황";
  const briefing = ready ? data.summary_briefing : kioskState.status === "waiting" ?
    (!congestionApiBase ? "센서 백엔드가 연결되면 실측 기반 목데이터를 볼 수 있어요. 랜덤 모드는 지금 이용할 수 있어요." : "1층 센서의 새 혼잡도 측정값을 기다리고 있어요. 수신되면 자동으로 표시됩니다.") :
    kioskState.status === "loading" ? "발권 흐름을 살펴보고 있어요…" : kioskState.status === "unconfigured" ? "로컬 서버에서 열면 키오스크 시연을 이용할 수 있어요." : "발권 분석을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.";
  if ($("kiosk-briefing").textContent !== briefing) $("kiosk-briefing").textContent = briefing;
  $("kiosk-briefing-box").classList.toggle("kiosk-alert", Boolean(ready && data.surge_momentum.is_surging));
  if (!ready) return;
  const s = data.staying_estimation, m = data.surge_momentum, g = data.golden_time_stats;
  $("kiosk-eating").textContent = s.current_eating;
  $("kiosk-leaving").textContent = s.leaving_in_10m;
  const reading = floorReading(activeLocation().floors.find(f => f.id === 1));
  $("kiosk-sensor").textContent = `1층 혼잡도 · ${measurementStyle(reading).name}`;
  $("kiosk-sensor-source").textContent = `${measurementSource(reading)}${Number.isFinite(reading.timestamp) ? " · " + preciseTimeFormat.format(reading.timestamp) : ""} / ${measuredMode ? "혼잡도 기반 가상 추정" : "가상 추정과 별도 자료"}`;
  $("kiosk-surge").textContent = m.surge_rate_percent === null ? "새 유입" : kioskSigned(m.surge_rate_percent);
  $("kiosk-surge").className = `kiosk-pill${m.is_surging ? " surge" : ""}`;
  $("kiosk-recent").textContent = m.recent_5m;
  $("kiosk-prev").textContent = `직전 5분 ${m.prev_5m}건${m.surge_rate_percent === null ? " · 증감률 산정 불가" : " 대비"}`;
  const values = s.total_5m_trend, max = Math.max(1, ...values);
  const points = values.map((v, i) => `${12 + i * 48},${65 - v / max * 50}`).join(" ");
  $("kiosk-chart").innerHTML = `<svg viewBox="0 0 264 80" role="img" aria-label="최근 30분 발권량, 과거부터 ${values.join(", ")}건"><path class="kiosk-chart-grid" d="M12 65H252 M12 40H252 M12 15H252"/><polyline class="kiosk-chart-line" points="${points}"/>${values.map((v, i) => `<circle cx="${12 + i * 48}" cy="${65 - v / max * 50}" r="3"/>`).join("")}</svg>`;
  $("kiosk-diff").textContent = g.diff_vs_usual_percent === null ? "—" : kioskSigned(g.diff_vs_usual_percent);
  $("kiosk-golden").textContent = g.recommended_time || (!data.operating ? "09:00 ~ 19:00" : "발권 흐름을 살펴보세요");
  $("kiosk-golden-tip").textContent = g.tip;
}

kioskModes.forEach((mode, index) => $(mode.id).addEventListener("click", () => {
  if (kioskState.mode === index) return;
  kioskState.mode = index;
  kioskState.payload = null;
  kioskState.status = "loading";
  void refreshKiosk();
}));
$("kiosk-retry").addEventListener("click", () => { void refreshKiosk(); });
