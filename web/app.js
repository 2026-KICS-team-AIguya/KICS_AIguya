"use strict";

const GRID_MS = 300000;
const state = {
  locationId: "sangnok", floorId: 2, angle: -35, flat: false,
  motion: !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  autoRefresh: true, lastUpdated: new Date(), step: 0, refreshing: false,
  snapshots: {}, connection: {},
  locations: CAMPUS_LOCATIONS.map(location => ({ ...location, floors: location.floors.map(floor => ({ ...floor, history: [] })) })),
};
const timeFormat = dateFormatter({ hour: "2-digit", minute: "2-digit", hour12: false });
const dateFormat = dateFormatter({ year: "numeric", month: "2-digit", day: "2-digit" });
const preciseTimeFormat = dateFormatter({ hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const numberFrames = new WeakMap();
let cameraFrame = 0;

function activeLocation() { return state.locations.find(location => location.id === state.locationId); }
function activeFloors() { return activeLocation().floors; }
function activeFloor() { return activeFloors().find(floor => floor.id === state.floorId); }

function animateNumber(element, value, suffix = "") {
  if (numberFrames.has(element)) cancelAnimationFrame(numberFrames.get(element));
  numberFrames.delete(element);
  if (!Number.isFinite(value)) { element.textContent = "—"; return; }
  const previous = parseInt(element.textContent, 10);
  if (!state.motion || !Number.isFinite(previous) || previous === value || !window.requestAnimationFrame) {
    element.textContent = `${value}${suffix}`;
    return;
  }
  const start = performance.now();
  function frame(now) {
    const progress = Math.min(1, (now - start) / 320);
    element.textContent = `${Math.round(previous + (value - previous) * (1 - (1 - progress) ** 3))}${suffix}`;
    if (progress < 1) numberFrames.set(element, requestAnimationFrame(frame));
    else numberFrames.delete(element);
  }
  numberFrames.set(element, requestAnimationFrame(frame));
}

function transitionContent(element) {
  if (state.motion && element?.animate) element.animate([{ opacity: .65, transform: "translateY(5px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 330, easing: "cubic-bezier(.2,.65,.25,1)" });
}

function initializeHistory() {
  const slot = Math.floor(Date.now() / GRID_MS) * GRID_MS;
  for (const location of state.locations) for (const floor of location.floors) {
    if (!floor.demo) continue;
    floor.history = floor.demo.history.map((level, index, values) => ({ timestamp: slot - (values.length - index - 1) * GRID_MS, level }));
  }
}

function advanceDemoFloors() {
  state.step += 1;
  const slot = Math.floor(Date.now() / GRID_MS) * GRID_MS;
  for (const location of state.locations) for (const floor of location.floors) {
    if (!floor.demo) continue;
    floor.demo = { ...floor.demo, level: floor.demo.pattern[Math.floor(state.step / 6) % floor.demo.pattern.length] };
    const latest = floor.history[floor.history.length - 1];
    if (latest?.timestamp === slot) latest.level = floor.demo.level;
    else floor.history.push({ timestamp: slot, level: floor.demo.level });
    floor.history = floor.history.filter(point => point.timestamp >= slot - 3600000);
  }
}

function renderFloors() {
  $("floor-cards").innerHTML = activeFloors().map(floor => {
    const reading = floorReading(floor), status = measurementStyle(reading);
    const source = measurementSource(reading);
    return `<button class="floor-card" type="button" data-floor="${floor.id}" aria-pressed="${floor.id === state.floorId}" aria-label="${floor.id}층 ${floor.name}, ${status.name}, ${source}">
      <div class="floor-card-heading"><span class="floor-number">${floor.id}층</span><span class="status-badge ${status.className}">${status.name}</span></div>
      <div class="floor-name">${floor.shortName}</div><div class="floor-metric floor-grade"><strong>${status.name}</strong><span>층 혼잡도</span></div>
      <div class="floor-card-footer"><span>${source}</span><strong>${reading.status === "ok" ? "상세 보기" : "측정 상태"}</strong></div></button>`;
  }).join("");
  $("floor-tabs").innerHTML = activeFloors().map(floor => `<button type="button" data-floor="${floor.id}" aria-pressed="${floor.id === state.floorId}">${floor.id}층</button>`).join("");
}

function renderPlan() {
  const floor = activeFloor();
  if (!floor) return;
  $("space-title").textContent = `${floor.id}층 · ${floor.name}`;
  $("floor-plan").setAttribute("aria-label", `${floor.id}층 식당 공간 일러스트. 실제 배치와 다릅니다.`);
  drawDiningRoom(floor, $("floor-plan"));
}

function renderDetail() {
  const floor = activeFloor(), reading = floorReading(floor), status = measurementStyle(reading);
  $("floor-title").textContent = `${floor.id}층`;
  $("floor-subtitle").textContent = `${activeLocation().name} · ${floor.name}`;
  $("floor-status").className = `status-badge ${status.className}`;
  $("floor-status").textContent = status.name;
  $("floor-level").textContent = reading.status === "ok" ? reading.level : "—";
  $("floor-confidence").textContent = reading.status === "ok" && Number.isFinite(reading.confidence) ? `${Math.round(reading.confidence * 100)}%` : "—";
  const source = measurementSource(reading);
  $("floor-data-status").textContent = source;
  $("floor-measured-at").textContent = Number.isFinite(reading.timestamp) ? preciseTimeFormat.format(reading.timestamp) : "수신 대기";
  $("floor-message").textContent = reading.status === "calibrating" ? `혼잡도를 확인하고 있어요. 준비까지 약 2분 · ${reading.progress || "진행 중"}` :
    reading.status === "ok" ? (source === "예시 데이터" ? "화면 안내를 위한 예시입니다." : source === "기록 데이터" ? "기록된 측정 자료를 보여드립니다." : "주변 상황에 따라 실제 혼잡도와 차이가 있을 수 있습니다.") :
    reading.status === "skipped" ? "혼잡도를 다시 확인하고 있어요. 잠시만 기다려 주세요." :
    reading.status === "stale" ? "새로운 측정 정보를 기다리고 있어요." : status.name;
}

function renderChart() {
  const floor = activeFloor();
  if (!floor) return;
  const reading = floorReading(floor), chart = $("trend-chart");
  $("chart-series-name").textContent = `${floor.id}층 ${floor.name} · ${measurementSource(reading)}`;
  const values = (reading.history || []).filter(point => Object.hasOwn(CONGESTION_LEVELS, point.level) && Number.isFinite(point.timestamp));
  if (!values.length) { chart.innerHTML = '<p class="chart-empty">측정 정보가 쌓이면 혼잡도 흐름을 보여드려요.</p>'; return; }
  const width = Math.max(240, chart.clientWidth), height = 180;
  const last = values[values.length - 1].timestamp, first = last - 3600000;
  const x = timestamp => 42 + (timestamp - first) / 3600000 * (width - 60);
  const y = level => ({ "여유": 140, "보통": 88, "혼잡": 36 }[level]);
  let previous;
  const line = values.map(point => {
    const command = !previous || point.timestamp - previous.timestamp > GRID_MS ? "M" : "L";
    previous = point;
    return `${command}${x(point.timestamp)},${y(point.level)}`;
  }).join(" ");
  chart.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="최근 한 시간 층별 혼잡 등급 추이">
    ${Object.keys(CONGESTION_LEVELS).map(level => `<line class="chart-grid" x1="42" y1="${y(level)}" x2="${width - 18}" y2="${y(level)}"/><text class="chart-axis-text" x="32" y="${y(level) + 4}" text-anchor="end">${level}</text>`).join("")}
    <path class="chart-line" d="${line}"/>${values.map(point => `<circle class="chart-point" cx="${x(point.timestamp)}" cy="${y(point.level)}" r="3.5"/>`).join("")}
    ${[first, first + 1800000, last].map((timestamp, index) => `<text class="chart-axis-text" x="${x(timestamp)}" y="175" text-anchor="${index === 0 ? "start" : index === 2 ? "end" : "middle"}">${timeFormat.format(timestamp)}</text>`).join("")}</svg>`;
}

function renderFacilities() {
  const location = activeLocation();
  $("facilities-title").textContent = `${location.name} 시설 안내`;
  $("facility-source").href = location.source;
  $("facility-grid").classList.toggle("single", !location.floors.length);
  $("facility-note").textContent = "운영시간·좌석 수·이용 대상은 확인 후 안내합니다.";
  $("facility-grid").innerHTML = location.floors.length ? location.floors.map(floor => `<article class="facility-card"><div class="facility-card-heading"><span class="facility-floor">${floor.id}층</span><h3>${floor.name}</h3></div><ul class="facility-list">${floor.dining.map(([name, type]) => `<li>${name}<span class="facility-type">${type}</span></li>`).join("")}</ul>${floor.amenities ? `<div class="amenities"><strong>함께 있는 편의시설</strong>${floor.amenities}</div>` : ""}<div class="facility-status">운영시간·이용 대상 확인 예정</div></article>`).join("") : `<article class="facility-card"><div class="facility-card-heading"><span class="facility-floor">${location.detail}</span><h3>${location.description}</h3></div><ul class="facility-list">${location.facilities.map(name => `<li>${name}</li>`).join("")}</ul></article>`;
}

function renderUpdatedAt() {
  $("today").textContent = dateFormat.format(new Date());
  $("updated-at").textContent = `${timeFormat.format(state.lastUpdated)} 확인 · ${state.autoRefresh ? "10초마다 갱신" : "일시정지"}`;
  $("auto-button").textContent = `자동 갱신 ${state.autoRefresh ? "켜짐" : "꺼짐"}`;
  $("auto-button").setAttribute("aria-pressed", String(state.autoRefresh));
  $("refresh-button").disabled = state.refreshing;
  $("connection-note").textContent = state.locationId === "sangnok" ? "혼잡도는 자동으로 갱신됩니다. 1·3층은 예시 데이터입니다." : "이 식당의 혼잡도는 제공 준비 중입니다.";
}

function renderDashboard() {
  const parentId = document.activeElement?.parentElement?.id, floorTarget = document.activeElement?.dataset.floor;
  const hasFloors = activeFloors().length > 0;
  $("dining-content").hidden = !hasFloors;
  $("pending-content").hidden = hasFloors;
  $("building-title").textContent = activeLocation().name;
  document.querySelector(".receipt-heading").textContent = `${activeLocation().name} / 층 현황`;
  renderKiosk();
  if (hasFloors) { renderFloors(); renderPlan(); renderDetail(); renderChart(); }
  renderUpdatedAt();
  if (parentId && floorTarget) $(parentId)?.querySelector(`[data-floor="${floorTarget}"]`)?.focus({ preventScroll: true });
}

function selectFloor(id) {
  if (!activeFloors().some(floor => floor.id === id)) return;
  state.floorId = id;
  renderDashboard(); renderWeeklyMenus();
  transitionContent($("floor-plan")); transitionContent($("trend-chart"));
  $("announcement").textContent = `${id}층 ${activeFloor().name} 혼잡도 현황을 표시합니다.`;
}

async function refreshDashboard(manual = false) {
  advanceDemoFloors();
  await refreshCongestion();
  renderDashboard();
  if (manual) $("announcement").textContent = "혼잡도와 발권 정보를 새로 확인했습니다.";
}
["floor-cards", "floor-tabs"].forEach(id => onClick(id, "[data-floor]", button => selectFloor(Number(button.dataset.floor))));
$("refresh-button").addEventListener("click", () => { void refreshDashboard(true); transitionContent($("location-detail")); });
$("auto-button").addEventListener("click", () => { state.autoRefresh = !state.autoRefresh; renderUpdatedAt(); });

function renderLocations() {
  $("location-count").textContent = `${state.locations.length}곳`;
  $("location-list").innerHTML = state.locations.map((location, index) => `<button type="button" class="location-option" data-location="${location.id}" aria-pressed="${location.id === state.locationId}"><span class="location-number">${String(index + 1).padStart(2, "0")}</span><span class="location-option-copy"><strong>${location.name}</strong><small>${location.description}</small></span><span class="location-option-status">${location.floors.length ? "층별 현황" : "준비 중"}</span></button>`).join("");
  $("selected-location-description").textContent = `${activeLocation().name} · ${activeLocation().detail}`;
  $("location-detail-link").innerHTML = `${activeLocation().name} 메뉴·현황 보기 <svg class="icon" aria-hidden="true"><use href="#i-arrow"/></svg>`;
}

function renderCampus() {
  drawCampus(state.locations, state.locationId, state.angle, state.flat);
  $("view-3d").setAttribute("aria-pressed", String(!state.flat)); $("view-flat").setAttribute("aria-pressed", String(state.flat));
  $("rotate-left").disabled = state.flat; $("rotate-right").disabled = state.flat;
}

function selectLocation(id) {
  const location = state.locations.find(item => item.id === id);
  if (!location) return;
  state.locationId = id;
  if (!location.floors.some(floor => floor.id === state.floorId)) state.floorId = location.floors[0]?.id ?? null;
  renderLocations(); renderDashboard(); renderFacilities(); renderCampus(); renderWeeklyMenus();
  transitionContent($("location-detail"));
  void refreshDashboard();
}
["campus-stage", "location-list"].forEach(id => onClick(id, "[data-location]", button => selectLocation(button.dataset.location)));

function initializeApp() {
  initializeHistory(); renderLocations(); renderFacilities(); renderDashboard(); renderCampus();
  setNavigation("campus"); initializeWeeklyMenus(); setMotion(state.motion);
  if ("IntersectionObserver" in window) {
    document.body.classList.add("motion-ready");
    const observer = new IntersectionObserver(entries => entries.forEach(entry => { if (entry.isIntersecting) { entry.target.classList.add("is-visible"); observer.unobserve(entry.target); } }), { threshold: .06 });
    document.querySelectorAll(".reveal").forEach(section => observer.observe(section));
  }
  if ("ResizeObserver" in window) {
    new ResizeObserver(renderChart).observe($("trend-chart"));
    new ResizeObserver(renderCampus).observe($("campus-stage"));
    new ResizeObserver(renderPlan).observe($("floor-plan"));
  } else window.addEventListener("resize", () => { renderChart(); renderCampus(); renderPlan(); });
  setInterval(() => { if (state.autoRefresh && !document.hidden) void refreshDashboard(); }, 10000);
  void refreshDashboard();
}

function setNavigation(id) {
  document.querySelectorAll("[data-nav]").forEach(link => {
    const active = link.dataset.nav === id;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "location");
    else link.removeAttribute("aria-current");
  });
}
document.querySelectorAll("[data-nav]").forEach(link => link.addEventListener("click", () => setNavigation(link.dataset.nav)));
if ("IntersectionObserver" in window) {
  const navigationObserver = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
    if (visible.length) setNavigation(visible[0].target.id);
  }, { rootMargin: "-5% 0px -65% 0px", threshold: 0 });
  ["campus", "location-detail", "facilities"].forEach(id => navigationObserver.observe($(id)));
}

function turnCampus(delta) {
  if (state.flat) return;
  if (cameraFrame) cancelAnimationFrame(cameraFrame);
  const target = state.angle + delta;
  if (!state.motion || !window.requestAnimationFrame) {
    state.angle = target;
    renderCampus();
    return;
  }
  const initial = state.angle;
  const start = performance.now();
  function frame(now) {
    const progress = Math.min(1, (now - start) / 480);
    state.angle = initial + delta * (1 - (1 - progress) ** 3);
    renderCampus();
    if (progress < 1) cameraFrame = requestAnimationFrame(frame);
    else cameraFrame = 0;
  }
  cameraFrame = requestAnimationFrame(frame);
}
function changeView(flat) {
  if (cameraFrame) cancelAnimationFrame(cameraFrame);
  cameraFrame = 0;
  state.flat = flat;
  renderCampus();
  transitionContent($("campus-scene"));
}
$("rotate-left").addEventListener("click", () => turnCampus(-30));
$("rotate-right").addEventListener("click", () => turnCampus(30));
$("view-3d").addEventListener("click", () => changeView(false));
$("view-flat").addEventListener("click", () => changeView(true));
$("reset-view").addEventListener("click", () => { state.angle = -35; changeView(false); });

function setMotion(enabled) {
  state.motion = enabled;
  document.body.classList.toggle("motion-off", !enabled);
  $("motion-button").setAttribute("aria-pressed", String(enabled));
  $("motion-button").setAttribute("aria-label", `장식 애니메이션 ${enabled ? "끄기" : "켜기"}`);
  $("motion-label").textContent = `움직임 ${enabled ? "켜짐" : "꺼짐"}`;
  if (!enabled) {
    if (cameraFrame) cancelAnimationFrame(cameraFrame);
    cameraFrame = 0;
    const element = $("ticket-count");
    if (numberFrames.has(element)) cancelAnimationFrame(numberFrames.get(element));
    numberFrames.delete(element);
    if (activeFloor()) renderDetail();
    renderKiosk();
    $("room-art-frame").style.setProperty("--tilt-x", "0deg");
    $("room-art-frame").style.setProperty("--tilt-y", "0deg");
  }
}
$("motion-button").addEventListener("click", () => setMotion(!state.motion));
const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)");
reducedMotion?.addEventListener?.("change", event => setMotion(!event.matches));
$("room-art-frame").addEventListener("pointermove", event => {
  if (!state.motion || event.pointerType === "touch") return;
  const rect = $("room-art-frame").getBoundingClientRect();
  $("room-art-frame").style.setProperty("--tilt-x", `${(event.clientX - rect.left - rect.width / 2) / rect.width * 5}deg`);
  $("room-art-frame").style.setProperty("--tilt-y", `${-(event.clientY - rect.top - rect.height / 2) / rect.height * 4}deg`);
});
$("room-art-frame").addEventListener("pointerleave", () => {
  $("room-art-frame").style.setProperty("--tilt-x", "0deg");
  $("room-art-frame").style.setProperty("--tilt-y", "0deg");
});


initializeApp();
