"use strict";

const GRID_MS = 5 * 60 * 1000;
const DEMO_STARTED_AT = Date.now();
const state = {
  locationId: "sangnok", angle: -35, flat: false,
  motion: !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  floorId: 2, zoneId: "A", autoRefresh: true, lastUpdated: new Date(DEMO_STARTED_AT), step: 0,
  locations: CAMPUS_LOCATIONS.map(location => ({
    ...location,
    kiosk: createKioskDemo(location.kiosk, DEMO_STARTED_AT),
    floors: location.floors.map(config => ({
      ...config,
      zones: config.initialOccupancy.map((occupancy, index) => ({
        id: String.fromCharCode(65 + index), name: `식사 구역 ${String.fromCharCode(65 + index)}`, occupancy,
      })),
      history: [...config.history],
    })),
  })),
};

const timeFormat = dateFormatter({ hour: "2-digit", minute: "2-digit", hour12: false });
const dateFormat = dateFormatter({ year: "numeric", month: "2-digit", day: "2-digit" });
const preciseTimeFormat = dateFormatter({ hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const numberFrames = new WeakMap();
let cameraFrame = 0;

function animateNumber(element, value, suffix = "%") {
  if (numberFrames.has(element)) cancelAnimationFrame(numberFrames.get(element));
  numberFrames.delete(element);
  if (!Number.isFinite(value)) {
    element.textContent = "—";
    return;
  }
  const previous = parseInt(element.textContent, 10);
  if (!state.motion || !Number.isFinite(previous) || previous === value || !window.requestAnimationFrame) {
    element.textContent = `${value}${suffix}`;
    return;
  }
  const start = performance.now();
  function frame(now) {
    const progress = Math.min(1, (now - start) / 320);
    const eased = 1 - (1 - progress) ** 3;
    element.textContent = `${Math.round(previous + (value - previous) * eased)}${suffix}`;
    if (progress < 1) numberFrames.set(element, requestAnimationFrame(frame));
    else numberFrames.delete(element);
  }
  numberFrames.set(element, requestAnimationFrame(frame));
}

function transitionContent(element) {
  if (!state.motion || !element?.animate) return;
  element.animate([{ opacity: .65, transform: "translateY(5px)" }, { opacity: 1, transform: "translateY(0)" }], { duration: 330, easing: "cubic-bezier(.2,.65,.25,1)" });
}

function level(value) {
  if (value >= 70) return { name: "혼잡", className: "busy", threshold: "70% 이상" };
  if (value > 30) return { name: "보통", className: "moderate", threshold: "30% 초과 · 70% 미만" };
  return { name: "여유", className: "free", threshold: "30% 이하" };
}

function occupancyOf(floor) {
  return Math.round(floor.zones.reduce((total, zone) => total + zone.occupancy, 0) / floor.zones.length);
}

function waitOf(floor) {
  const occupancy = occupancyOf(floor);
  // 실측 대기시간 모델을 연결하기 전의 시연용 계산이다.
  if (floor.id === 1) {
    const low = Math.max(1, Math.round(occupancy / 12));
    return `${low}–${low + 4}분`;
  }
  return `${Math.max(1, Math.round(occupancy * 0.15))}분`;
}

function activeLocation() { return state.locations.find(location => location.id === state.locationId); }
function activeFloors() { return activeLocation().floors; }
function activeFloor() { return activeFloors().find(floor => floor.id === state.floorId); }
function allFloors() { return state.locations.flatMap(location => location.floors); }

function initializeHistory() {
  const slot = Math.floor(state.lastUpdated.getTime() / GRID_MS) * GRID_MS;
  for (const floor of allFloors()) {
    floor.history = floor.history.map((value, index) => ({ timestamp: slot - (12 - index) * GRID_MS, value }));
    floor.history.push({ timestamp: slot, value: occupancyOf(floor) });
  }
}

function renderFloors() {
  $("floor-cards").innerHTML = activeFloors().map(floor => {
    const occupancy = occupancyOf(floor);
    const status = level(occupancy);
    const selected = floor.id === state.floorId;
    return `<button class="floor-card" type="button" data-floor="${floor.id}" aria-pressed="${selected}" aria-label="${floor.id}층 ${floor.name}, ${status.name}, 점유율 ${occupancy}%, 상세 보기">
      <div class="floor-card-heading"><span class="floor-number">${floor.id}층</span><span class="status-badge ${status.className}">${status.name}</span></div>
      <div class="floor-name">${floor.shortName}</div><div class="floor-metric"><strong>${occupancy}%</strong><span>점유율</span></div>
      <div class="floor-card-footer"><span>${floor.waitLabel}</span><strong>${waitOf(floor)}</strong></div>
    </button>`;
  }).join("");
  $("floor-tabs").innerHTML = activeFloors().map(floor => `<button type="button" data-floor="${floor.id}" aria-pressed="${floor.id === state.floorId}" aria-label="${floor.id}층 ${floor.name}">${floor.id}층</button>`).join("");
}

function renderPlan() {
  const floor = activeFloor();
  $("space-title").textContent = `${floor.id}층 · ${floor.name}`;
  $("floor-plan").setAttribute("aria-label", `${activeLocation().name} ${floor.id}층 임시 식사 공간 구역도. 실제 평면도와 다릅니다.`);
  drawDiningRoom(floor, state.zoneId, $("floor-plan"));
}

function renderDetail() {
  const floor = activeFloor();
  const zone = floor.zones.find(item => item.id === state.zoneId);
  const status = level(zone.occupancy);
  $("zone-title").textContent = `${zone.id}구역`;
  $("zone-subtitle").textContent = `${activeLocation().name} ${floor.id}층 · ${zone.name}`;
  $("zone-status").className = `status-badge ${status.className}`;
  $("zone-status").textContent = status.name;
  animateNumber($("zone-occupancy"), zone.occupancy);
  $("zone-threshold").textContent = status.threshold;
  $("zone-data-status").textContent = state.autoRefresh ? "더미 · 자동 갱신" : "더미 · 일시정지";
  $("zone-progress").className = status.className;
  $("zone-progress").style.width = `${zone.occupancy}%`;
}

function renderChart() {
  if (activeLocation().mode !== "demo") return;
  const floor = activeFloor();
  const chart = $("trend-chart");
  const width = Math.max(220, chart.clientWidth);
  const height = 180;
  const padding = { left: 32, right: 20, top: 26, bottom: 28 };
  const values = floor.history;
  const first = values[0].timestamp;
  const last = values[values.length - 1].timestamp;
  const x = timestamp => padding.left + ((timestamp - first) / (last - first)) * (width - padding.left - padding.right);
  const y = value => height - padding.bottom - value / 100 * (height - padding.top - padding.bottom);
  const points = values.map(point => `${x(point.timestamp).toFixed(1)},${y(point.value).toFixed(1)}`);
  const line = `M${points.join(" L")}`;
  const area = `${line} L${x(last)},${y(0)} L${x(first)},${y(0)} Z`;
  const tickIndexes = width < 450 ? [0, 6, 12] : [0, 3, 6, 9, 12];
  const current = values[values.length - 1];
  chart.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="trend-title trend-description">
    <title id="trend-title">${floor.id}층 ${floor.name}의 최근 1시간 점유율</title>
    <desc id="trend-description">시연용 더미 이력. 가로축은 한국 시간, 세로축은 점유율 0에서 100퍼센트. 현재 ${current.value}퍼센트.</desc>
    <defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ad7950" stop-opacity=".16"/><stop offset="100%" stop-color="#ad7950" stop-opacity="0"/></linearGradient></defs>
    ${[0, 50, 100].map(value => `<line class="chart-grid" x1="${padding.left}" y1="${y(value)}" x2="${width - padding.right}" y2="${y(value)}"/><text class="chart-axis-text" x="${padding.left - 8}" y="${y(value) + 4}" text-anchor="end">${value}</text>`).join("")}
    <path d="${area}" fill="url(#trend-fill)"/><path class="chart-line" d="${line}"/>
    ${tickIndexes.map((index, tick) => `<text class="chart-axis-text" x="${x(values[index].timestamp)}" y="${height - 5}" text-anchor="${tick === 0 ? "start" : tick === tickIndexes.length - 1 ? "end" : "middle"}">${timeFormat.format(values[index].timestamp)}</text>`).join("")}
    <circle class="chart-point" cx="${x(last)}" cy="${y(current.value)}" r="4.5"/><text class="chart-last-label" x="${x(last) - 7}" y="${y(current.value) - 12}" text-anchor="end">${current.value}%</text>
  </svg>`;
  $("chart-series-name").textContent = `${floor.id}층 ${floor.name}`;
}

function renderFacilities() {
  const location = activeLocation();
  $("facilities-title").textContent = `${location.name} 시설 안내`;
  $("facility-source").href = location.source;
  $("facility-grid").classList.toggle("single", location.mode !== "demo");
  $("facility-note").textContent = "운영시간·좌석 수·이용 대상은 확인 후 안내합니다.";
  if (location.mode !== "demo") {
    $("facility-grid").innerHTML = `<article class="facility-card"><div class="facility-card-heading"><span class="facility-floor">${location.detail}</span><h3>${location.description}</h3></div><ul class="facility-list">${location.facilities.map(name => `<li>${name}</li>`).join("")}</ul></article>`;
    return;
  }
  $("facility-grid").innerHTML = activeFloors().map(floor => `<article class="facility-card">
    <div class="facility-card-heading"><span class="facility-floor">${floor.id}층</span><h3>${floor.name}</h3></div>
    <ul class="facility-list">${floor.dining.map(([name, type]) => `<li>${name}<span class="facility-type">${type}</span></li>`).join("")}</ul>
    ${floor.amenities ? `<div class="amenities"><strong>함께 있는 편의시설</strong>${floor.amenities}</div>` : ""}
    <div class="facility-status">${floor.id === 3 ? "운영시간·이용 대상 확인 예정" : "운영시간 확인 예정"}</div>
  </article>`).join("");
}

function renderStores() {
  const floor = activeFloor();
  $("store-panel").hidden = floor.id !== 1;
  if (floor.id !== 1) return;
  const baseline = Math.max(1, Math.round(occupancyOf(floor) / 12));
  $("store-cards").innerHTML = floor.dining.map(([name, type], index) => `<div class="store-card"><div><strong>${name}</strong><span>${type}</span></div><p><strong>${baseline + index * 2}</strong>분<small>예상 주문 대기</small></p></div>`).join("");
}

function renderUpdatedAt() {
  $("today").textContent = dateFormat.format(state.lastUpdated);
  $("updated-at").textContent = `${timeFormat.format(state.lastUpdated)} · ${state.autoRefresh ? "10초마다 갱신" : "일시정지"}`;
  $("auto-button").textContent = `자동 갱신 ${state.autoRefresh ? "켜짐" : "꺼짐"}`;
  $("auto-button").setAttribute("aria-pressed", String(state.autoRefresh));
}

function renderKiosk() {
  const summary = getKioskSummary(activeLocation().kiosk, state.lastUpdated.getTime());
  const direction = summary?.change > 0 ? "rising" : summary?.change < 0 ? "falling" : "steady";
  $("ticket-change").className = `ticket-change ${direction}`;
  $("ticket-asof").textContent = `${preciseTimeFormat.format(state.lastUpdated)} 기준 · ${summary?.scope || activeLocation().name}`;
  animateNumber($("ticket-count"), summary ? summary.recent : NaN, "");
  if (!summary) {
    $("ticket-change").textContent = "";
    $("ticket-hint").textContent = "발권 데이터 없음";
    $("ticket-previous").textContent = "—";
    $("ticket-recent").textContent = "—";
    $("ticket-previous-bar").style.width = "0%";
    $("ticket-recent-bar").style.width = "0%";
    return;
  }
  const signed = value => `${value > 0 ? "+" : ""}${value}`;
  $("ticket-change").textContent = summary.change === 0 ? "변동 없음" : `${signed(summary.change)}건${summary.percent === null ? "" : ` (${signed(summary.percent)}%)`}`;
  const trend = summary.change > 0 ? "직전 5분보다 발권이 늘었어요." : summary.change < 0 ? "직전 5분보다 발권이 줄었어요." : "직전 5분과 발권량이 같아요.";
  $("ticket-hint").textContent = `${trend} 좌석 점유율도 함께 살펴보세요.`;
  $("ticket-previous").textContent = `${summary.previous}건`;
  $("ticket-recent").textContent = `${summary.recent}건`;
  const ceiling = Math.max(1, summary.previous, summary.recent);
  $("ticket-previous-bar").style.width = `${summary.previous / ceiling * 100}%`;
  $("ticket-recent-bar").style.width = `${summary.recent / ceiling * 100}%`;
}

// 자동 갱신으로 버튼을 다시 만들 때 키보드 포커스를 복원한다.
function renderDashboard() {
  const focused = document.activeElement;
  const parentId = focused?.parentElement?.id;
  const floorTarget = focused?.dataset.floor;
  const zoneTarget = focused?.dataset.zone;
  const demo = activeLocation().mode === "demo";
  $("demo-content").hidden = !demo;
  $("pending-content").hidden = demo;
  $("demo-actions").hidden = !demo;
  $("building-title").textContent = activeLocation().name;
  document.querySelector(".receipt-heading").textContent = `${activeLocation().name} / 구역 현황`;
  if (demo) {
    renderFloors(); renderKiosk(); renderPlan(); renderDetail(); renderStores(); renderChart();
  }
  renderUpdatedAt();
  if (floorTarget && parentId) {
    $(parentId)?.querySelector(`[data-floor="${floorTarget}"]`)?.focus({ preventScroll: true });
  } else if (zoneTarget) {
    $("floor-plan").querySelector(`button[data-zone="${zoneTarget}"]`)?.focus({ preventScroll: true });
  }
}

function selectFloor(id) {
  if (!activeFloors().some(floor => floor.id === id)) return;
  state.floorId = id;
  state.zoneId = "A";
  renderDashboard();
  renderWeeklyMenus();
  transitionContent($("floor-plan"));
  transitionContent($("trend-chart"));
  $("announcement").textContent = `${id}층 ${activeFloor().name}을 선택했습니다. A구역 상세를 표시합니다.`;
}

function refreshDemo(manual = false) {
  state.step += 1;
  state.lastUpdated = new Date();
  const slot = Math.floor(state.lastUpdated.getTime() / GRID_MS) * GRID_MS;
  state.locations.forEach(location => advanceKioskDemo(location.kiosk, state.lastUpdated.getTime()));
  for (const floor of allFloors()) {
    floor.zones.forEach((zone, index) => {
      const variation = Math.round(Math.sin(state.step * 0.67 + floor.id + index * 1.3) * 4);
      zone.occupancy = Math.max(0, Math.min(100, floor.initialOccupancy[index] + variation));
    });
    const latest = floor.history[floor.history.length - 1];
    const current = occupancyOf(floor);
    if (latest.timestamp === slot) latest.value = current;
    else {
      // 오래 멈췄던 경우에도 화면에 필요한 한 시간만 보충한다.
      const firstSlot = Math.max(latest.timestamp + GRID_MS, slot - 12 * GRID_MS);
      for (let timestamp = firstSlot; timestamp <= slot; timestamp += GRID_MS) {
        floor.history.push({ timestamp, value: timestamp === slot ? current : latest.value });
      }
      floor.history = floor.history.slice(-13);
    }
  }
  renderDashboard();
  if (manual) $("announcement").textContent = "더미 데이터를 새로고침했습니다.";
}

["floor-cards", "floor-tabs"].forEach(id => {
  onClick(id, "[data-floor]", button => selectFloor(Number(button.dataset.floor)));
});
onClick("floor-plan", "[data-zone]", button => {
  if (activeLocation().mode !== "demo") return;
  state.zoneId = button.dataset.zone;
  const restoreFocus = $("floor-plan").contains(document.activeElement);
  renderPlan();
  if (restoreFocus) $("floor-plan").querySelector(`button[data-zone="${state.zoneId}"]`)?.focus({ preventScroll: true });
  renderDetail();
  transitionContent(document.querySelector(".zone-detail"));
  const selected = activeFloor().zones.find(zone => zone.id === state.zoneId);
  $("announcement").textContent = `${state.zoneId}구역, ${selected.occupancy}%, ${level(selected.occupancy).name}`;
});
$("refresh-button").addEventListener("click", () => {
  refreshDemo(true);
  $("refresh-button").classList.remove("refreshing");
  if (state.motion) {
    void $("refresh-button").offsetWidth;
    $("refresh-button").classList.add("refreshing");
  }
});
$("auto-button").addEventListener("click", () => {
  state.autoRefresh = !state.autoRefresh;
  renderUpdatedAt();
  if (activeLocation().mode === "demo") renderDetail();
  $("announcement").textContent = state.autoRefresh ? "더미 자동 갱신을 켰습니다." : "더미 자동 갱신을 일시정지했습니다.";
});

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

function renderLocations() {
  $("location-count").textContent = `${state.locations.length}곳`;
  $("location-list").innerHTML = state.locations.map((location, index) => `<button type="button" class="location-option" data-location="${location.id}" aria-pressed="${location.id === state.locationId}" aria-label="${location.name}, ${location.mode === "demo" ? "더미 혼잡도 보기" : "혼잡도 준비 중"}"><span class="location-number">${String(index + 1).padStart(2, "0")}</span><span class="location-option-copy"><strong>${location.name}</strong><small>${location.description}</small></span><span class="location-option-status ${location.mode}">${location.mode === "demo" ? "시연 중" : "준비 중"}</span></button>`).join("");
  const location = activeLocation();
  $("selected-location-description").textContent = `${location.name} · ${location.detail}`;
  $("location-detail-link").innerHTML = `${location.name} ${location.mode === "demo" ? "메뉴·현황" : "메뉴"} 보기 <svg class="icon" aria-hidden="true"><use href="#i-arrow"/></svg>`;
}

function renderCampus() {
  drawCampus(state.locations, state.locationId, state.angle, state.flat);
  $("view-3d").setAttribute("aria-pressed", String(!state.flat));
  $("view-flat").setAttribute("aria-pressed", String(state.flat));
  $("rotate-left").disabled = state.flat;
  $("rotate-right").disabled = state.flat;
}

function selectLocation(id) {
  const location = state.locations.find(item => item.id === id);
  if (!location) return;
  const wasLocationList = $("location-list").contains(document.activeElement);
  state.locationId = id;
  if (location.mode === "demo" && !location.floors.some(floor => floor.id === state.floorId)) {
    state.floorId = location.floors[0].id;
    state.zoneId = "A";
  }
  renderLocations();
  renderDashboard();
  renderFacilities();
  renderCampus();
  renderWeeklyMenus();
  transitionContent($("location-detail"));
  if (wasLocationList) $("location-list").querySelector(`[data-location="${id}"]`)?.focus({ preventScroll: true });
  $("announcement").textContent = `${location.name} 선택. ${location.mode === "demo" ? "층별 더미 혼잡도를 표시합니다." : "혼잡도 준비 중. 시설 정보만 표시합니다."}`;
}

["campus-stage", "location-list"].forEach(id => {
  onClick(id, "[data-location]", button => selectLocation(button.dataset.location));
});
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
    if (activeLocation().mode === "demo") {
      const element = $("zone-occupancy");
      if (numberFrames.has(element)) cancelAnimationFrame(numberFrames.get(element));
      numberFrames.delete(element);
      renderDetail();
      renderKiosk();
    }
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

function initializeApp() {
  initializeHistory();
  renderLocations();
  renderFacilities();
  renderDashboard();
  renderCampus();
  setNavigation("campus");
  initializeWeeklyMenus();
  setMotion(state.motion);

  if ("IntersectionObserver" in window) {
    document.body.classList.add("motion-ready");
    const revealObserver = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: .06 });
    document.querySelectorAll(".reveal").forEach(section => revealObserver.observe(section));
  }
  if ("ResizeObserver" in window) {
    new ResizeObserver(renderChart).observe($("trend-chart"));
    new ResizeObserver(renderCampus).observe($("campus-stage"));
    new ResizeObserver(() => {
      if (activeLocation().mode === "demo") renderPlan();
    }).observe($("floor-plan"));
  } else {
    window.addEventListener("resize", () => {
      renderChart();
      renderCampus();
      if (activeLocation().mode === "demo") renderPlan();
    });
  }
  setInterval(() => {
    if (state.autoRefresh && !document.hidden) refreshDemo();
  }, 10000);
}

initializeApp();
