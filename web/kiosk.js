"use strict";

function renderKiosk() {
  const connected = state.connection[state.locationId] === "connected";
  const summary = connected ? state.snapshots[state.locationId]?.kiosk : null;
  const validCount = value => Number.isInteger(value) && value >= 0;
  const recent = summary?.status === "ok" && validCount(summary.recent) ? summary.recent : null;
  const previous = summary?.status === "ok" && validCount(summary.previous) ? summary.previous : null;
  const change = recent !== null && previous !== null ? recent - previous : null;
  const direction = change > 0 ? "rising" : change < 0 ? "falling" : "steady";
  $("ticket-change").className = `ticket-change ${direction}`;
  $("ticket-asof").textContent = `${activeLocation().name} 전체 · ${Number.isFinite(summary?.as_of) ? preciseTimeFormat.format(summary.as_of) + " 기준" : "수집 준비 중"}`;
  animateNumber($("ticket-count"), recent === null ? NaN : recent);
  $("ticket-previous").textContent = previous === null ? "—" : `${previous}건`;
  $("ticket-recent").textContent = recent === null ? "—" : `${recent}건`;
  const ceiling = Math.max(1, previous || 0, recent || 0);
  $("ticket-previous-bar").style.width = `${(previous || 0) / ceiling * 100}%`;
  $("ticket-recent-bar").style.width = `${(recent || 0) / ceiling * 100}%`;
  $("ticket-change").textContent = "";
  if (recent === null) {
    $("ticket-hint").textContent = summary?.status === "stale" ? "발권 데이터 수신이 끊겼습니다." : summary?.status === "collecting" ? "5분 구간을 수집 중입니다. 누락된 구간은 0건으로 계산하지 않습니다." : "발권 데이터 수집 준비 중입니다.";
    return;
  }
  if (change === null) { $("ticket-hint").textContent = "직전 5분 데이터가 쌓이면 증감도 함께 보여드려요."; return; }
  const sign = value => `${value > 0 ? "+" : ""}${value}`;
  const percent = previous ? Math.round(change / previous * 100) : null;
  $("ticket-change").textContent = change === 0 ? "변동 없음" : `${sign(change)}건${percent === null ? "" : ` (${sign(percent)}%)`}`;
  $("ticket-hint").textContent = change > 0 ? "직전 5분보다 발권이 늘었어요. 층별 혼잡도도 함께 살펴보세요." : change < 0 ? "직전 5분보다 발권이 줄었어요." : "직전 5분과 발권량이 같아요.";
}
