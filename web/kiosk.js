"use strict";

const kioskModes = [
  { label: "실시간", detail: "현재 시각", query: "" },
  { label: "12:00", detail: "점심 피크", query: "?test_hour=12&test_minute=0" },
  { label: "11:30", detail: "유입 시작", query: "?test_hour=11&test_minute=30" },
  { label: "15:00", detail: "한산한 오후", query: "?test_hour=15&test_minute=0" },
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
  return data?.version === 1 && data.data_source === "mock" && data.location_id === "sangnok" && data.floor === 2 &&
    typeof data.summary_briefing === "string" && typeof data.operating === "boolean" && Number.isFinite(Date.parse(data.as_of)) &&
    s && count(s.current_eating) && count(s.leaving_in_10m) && s.leaving_in_10m <= s.current_eating &&
    Array.isArray(s.total_5m_trend) && s.total_5m_trend.length === 6 && s.total_5m_trend.every(count) &&
    m && optional(m.surge_rate_percent) && typeof m.is_surging === "boolean" && count(m.recent_5m) && count(m.prev_5m) &&
    g && optional(g.diff_vs_usual_percent) && (g.recommended_time === null || typeof g.recommended_time === "string") && typeof g.tip === "string" &&
    ["korean", "special", "noodle"].every(key => {
      const c = data.corners?.[key];
      return c && typeof c.name === "string" && typeof c.menu === "string" && count(c.remaining_stock) && count(c.daily_limit) && c.daily_limit > 0 &&
        c.remaining_stock <= c.daily_limit && finite(c.wait_time_min) && c.wait_time_min >= 0 && typeof c.sold_out === "boolean" &&
        ["SMOOTH", "NORMAL", "CONGESTED"].includes(c.status) && (c.mins_to_sold_out === null || count(c.mins_to_sold_out)) &&
        (c.expected_sold_out_time === null || /^\d{2}:\d{2}$/.test(c.expected_sold_out_time));
    });
}

async function refreshKiosk() {
  const request = ++kioskState.request;
  kioskState.controller?.abort();
  if (state.locationId !== "sangnok") return;
  if (!kioskEndpoint) { kioskState.status = "unconfigured"; renderKiosk(); return; }
  const controller = new AbortController();
  kioskState.controller = controller;
  const timeout = setTimeout(() => controller.abort(), 8000);
  if (!kioskState.payload) kioskState.status = "loading";
  renderKiosk();
  try {
    const response = await fetch(`${kioskEndpoint}${kioskModes[kioskState.mode].query}`, { signal: controller.signal, cache: "no-store" });
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
  $("kiosk-service").hidden = !visible;
  $("kiosk-mode").hidden = !visible;
  if (!visible) return;
  const mode = kioskModes[kioskState.mode];
  $("kiosk-mode-label").textContent = `${mode.label} · ${mode.detail}`;
  $("kiosk-mode").setAttribute("aria-label", `시연 시간 ${mode.label}. 누르면 ${kioskModes[(kioskState.mode + 1) % kioskModes.length].label} 모드로 전환`);
  const data = kioskState.payload;
  const ready = kioskState.status === "ready" && data;
  $("kiosk-results").hidden = !ready;
  $("kiosk-retry").hidden = !["error", "unconfigured"].includes(kioskState.status);
  $("kiosk-asof").textContent = ready ? `${timeFormat.format(new Date(data.as_of))} 기준 · ${data.operating ? "가상 운영 중" : "가상 운영 종료"}` : "상록원 2층 · 가상 코너 3곳";
  const briefing = ready ? data.summary_briefing : kioskState.status === "loading" ? "발권 흐름을 살펴보고 있어요…" : kioskState.status === "unconfigured" ? "로컬 서버에서 열면 키오스크 시연을 이용할 수 있어요." : "발권 분석을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.";
  if ($("kiosk-briefing").textContent !== briefing) $("kiosk-briefing").textContent = briefing;
  $("kiosk-briefing-box").classList.toggle("kiosk-alert", Boolean(ready && data.surge_momentum.is_surging));
  if (!ready) return;
  const s = data.staying_estimation, m = data.surge_momentum, g = data.golden_time_stats;
  $("kiosk-eating").textContent = s.current_eating;
  $("kiosk-leaving").textContent = s.leaving_in_10m;
  const reading = floorReading(activeLocation().floors.find(f => f.id === 2));
  $("kiosk-sensor").textContent = `2층 CSI · ${measurementStyle(reading).name}`;
  $("kiosk-sensor-source").textContent = `${measurementSource(reading)}${Number.isFinite(reading.timestamp) ? " · " + preciseTimeFormat.format(reading.timestamp) : ""} / 가상 추정과 별도 자료`;
  $("kiosk-surge").textContent = m.surge_rate_percent === null ? "새 유입" : kioskSigned(m.surge_rate_percent);
  $("kiosk-surge").className = `kiosk-pill${m.is_surging ? " surge" : ""}`;
  $("kiosk-recent").textContent = m.recent_5m;
  $("kiosk-prev").textContent = `직전 5분 ${m.prev_5m}건${m.surge_rate_percent === null ? " · 증감률 산정 불가" : " 대비"}`;
  const values = s.total_5m_trend, max = Math.max(1, ...values);
  const points = values.map((v, i) => `${12 + i * 48},${65 - v / max * 50}`).join(" ");
  $("kiosk-chart").innerHTML = `<svg viewBox="0 0 264 80" role="img" aria-label="최근 30분 발권량, 과거부터 ${values.join(", ")}건"><path class="kiosk-chart-grid" d="M12 65H252 M12 40H252 M12 15H252"/><polyline class="kiosk-chart-line" points="${points}"/>${values.map((v, i) => `<circle cx="${12 + i * 48}" cy="${65 - v / max * 50}" r="3"/>`).join("")}</svg>`;
  $("kiosk-diff").textContent = g.diff_vs_usual_percent === null ? "—" : kioskSigned(g.diff_vs_usual_percent);
  const hasStock = Object.values(data.corners).some(c => !c.sold_out);
  $("kiosk-golden").textContent = g.recommended_time || (!data.operating ? "09:00 ~ 19:00" : hasStock ? "지금 코너를 비교해요" : "오늘 준비 수량 소진");
  $("kiosk-golden-tip").textContent = data.operating && !hasStock ? "다른 시연 시간을 선택해 주세요." : g.tip;
  $("kiosk-corners").innerHTML = ["korean", "special", "noodle"].map((key, i) => {
    const c = data.corners[key];
    const labels = { SMOOTH: "원활", NORMAL: "보통", CONGESTED: "혼잡" };
    const status = !data.operating ? "closed" : c.sold_out ? "sold" : c.status.toLowerCase();
    const label = !data.operating ? "운영 종료" : c.sold_out ? "품절" : labels[c.status];
    const urgent = data.operating && !c.sold_out && c.mins_to_sold_out !== null && c.mins_to_sold_out <= 20;
    const stockNote = !data.operating ? "다음 운영시간에 만나요" : c.sold_out ? "오늘 준비한 수량이 모두 소진됐어요" : c.mins_to_sold_out !== null && c.mins_to_sold_out <= 60 ? `약 ${c.mins_to_sold_out}분 뒤 · ${c.expected_sold_out_time} 품절 예상` : c.mins_to_sold_out === null ? "현재 속도로는 운영 중 품절 전망이 없어요" : "현재 속도로는 1시간 이상 여유가 있어요";
    return `<article class="kiosk-corner ${status}"><div class="kiosk-corner-top"><span class="kiosk-corner-number">0${i + 1}</span><span class="kiosk-traffic ${status}"><i aria-hidden="true"></i>${label}</span></div><h4>${escapeHtml(c.name)}</h4><p class="kiosk-menu">${escapeHtml(c.menu)}</p><p class="kiosk-wait"><strong>${!data.operating || c.sold_out ? "—" : c.wait_time_min}</strong><span>분 <small>예상 배식 대기</small></span></p><div class="kiosk-stock-label"><span>남은 수량</span><span><strong>${c.remaining_stock}</strong> / ${c.daily_limit}개</span></div><progress value="${c.remaining_stock}" max="${c.daily_limit}" aria-label="${escapeHtml(c.name)} 남은 수량">${c.remaining_stock} / ${c.daily_limit}</progress><p class="kiosk-stock-note${urgent ? " urgent" : ""}">${stockNote}</p></article>`;
  }).join("");
}

$("kiosk-mode").addEventListener("click", () => {
  kioskState.mode = (kioskState.mode + 1) % kioskModes.length;
  kioskState.payload = null;
  kioskState.status = "loading";
  void refreshKiosk();
});
$("kiosk-retry").addEventListener("click", () => { void refreshKiosk(); });
