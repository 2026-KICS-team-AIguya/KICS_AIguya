"use strict";

const menuApiBase = window.DINING_API_BASE || (window.location.pathname.startsWith("/dashboard") ? window.location.origin : null);
const menuState = { catalog: window.DINING_MENU_CACHE || { version: 1, locations: {} }, selectedDate: null, selectedLocation: null, refreshing: false, fetchFailed: false };
const menuDateFormat = dateFormatter({ month: "2-digit", day: "2-digit", weekday: "short" });
const menuCheckedFormat = dateFormatter({ year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
const menuIsoDateFormat = dateFormatter({ year: "numeric", month: "2-digit", day: "2-digit" }, "en-CA");

function todayInSeoul(now = new Date()) {
  const parts = menuIsoDateFormat.formatToParts(now);
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function officialMenuUrl(value) {
  try {
    const url = new URL(value);
    const origins = ["https://www.dongguk.edu", "https://dorm.dongguk.edu", "https://dgucoop.dongguk.edu:44649"];
    return origins.includes(url.origin) && !url.username && !url.password ? url.href : null;
  } catch { return null; }
}

function menuAsset(value) {
  if (/^assets\/menus\/[a-f0-9]{16}\.(png|jpg|gif|webp)$/.test(value || "")) return value;
  if (typeof value !== "string" || !value.startsWith("/api/menu-image?")) return null;
  try {
    const image = new URL(value, window.location.origin);
    return image.origin === window.location.origin && image.pathname === "/api/menu-image" && officialMenuUrl(image.searchParams.get("source")) ? value : null;
  } catch { return null; }
}

function menuAvailability(menu, today = todayInSeoul(), now = new Date()) {
  if (!menu || menu.status === "error" || !menu.fetchedAt) return { className: "unavailable", label: "확인 필요", message: "식단표를 확인하지 못했습니다. 공식 안내를 확인해 주세요." };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(menu.periodStart || "") || !/^\d{4}-\d{2}-\d{2}$/.test(menu.periodEnd || "")) return { className: "unavailable", label: "기간 확인 필요", message: "식단표의 적용 기간을 확인할 수 없습니다." };
  if (menu.periodEnd < today) return { className: "past", label: "지난 식단", message: "현재 날짜에 해당하는 식단이 아닙니다. 최신 게시 여부를 공식 안내에서 확인해 주세요." };
  if (menu.periodStart > today) return { className: "upcoming", label: "예정 식단", message: "앞으로 적용될 식단표입니다. 표시된 기간을 확인해 주세요." };
  const age = now.getTime() - new Date(menu.fetchedAt).getTime();
  if (menu.status === "stale" || !Number.isFinite(age) || age > 86400000 || menuState.fetchFailed) return { className: "stale", label: "저장된 식단", message: "새로 확인하지 못했거나 확인한 지 하루가 지난 자료입니다. 공식 안내도 함께 확인해 주세요." };
  return { className: "current", label: "공식 식단", message: menuApiBase ? "학교 공식 자료를 기준으로 업데이트합니다." : "저장된 공식 식단표입니다. 이후 변경은 공식 안내를 확인해 주세요." };
}

function menuLine(line) {
  const className = /\d{1,2}:\d{2}\s*[~～–-]/.test(line) ? "menu-time" : /^\([^)]*[:：]/.test(line) ? "menu-origin" : "";
  return `<li${className ? ` class="${className}"` : ""}>${escapeHtml(line)}</li>`;
}

function renderMenuHeader(location, menu, availability) {
  $("menu-title").textContent = `${location.name} 주간 식단`;
  $("menu-status").className = `menu-status ${availability.className}`;
  $("menu-status").textContent = availability.label;
  $("menu-message").textContent = availability.message;
  $("menu-source").href = officialMenuUrl(menu?.sourceUrl) || location.menuSource;
  $("menu-period").textContent = menu?.periodStart && menu?.periodEnd ? `${menu.periodStart.replaceAll("-", ".")} – ${menu.periodEnd.replaceAll("-", ".")}` : "적용 기간 확인 필요";
  const checked = menu?.fetchedAt ? new Date(menu.fetchedAt) : null;
  $("menu-checked").textContent = checked && Number.isFinite(checked.getTime()) ? `공식 자료 확인 ${menuCheckedFormat.format(checked)}` : "확인한 자료 없음";
  $("menu-refresh").hidden = !menuApiBase;
  $("menu-refresh").disabled = menuState.refreshing;
  $("menu-refresh").textContent = menuState.refreshing ? "확인 중…" : "새로 확인";
  $("menu-floor-field").hidden = menu?.format !== "table";
  $("menu-date-tabs").hidden = menu?.format !== "table";
  $("menu-date-tabs").innerHTML = "";
  $("menu-attachments").innerHTML = "";

}

function menuEntryMarkup(entry) {
  const lines = Array.isArray(entry.lines) ? entry.lines : [];
  const remaining = lines.slice(5);
  const details = remaining.length
    ? `<details><summary>메뉴 전체 보기</summary><ul>${remaining.map(menuLine).join("")}</ul></details>`
    : "";
  const price = entry.price ? `<p class="menu-price">${escapeHtml(entry.price)}</p>` : "";
  return `<article class="daily-menu">
    <div class="daily-menu-heading"><h4>${escapeHtml(entry.corner)}</h4><span>${escapeHtml(entry.meal)}</span></div>
    <ul>${lines.slice(0, 5).map(menuLine).join("")}</ul>${details}${price}
  </article>`;
}

function renderTableMenu(menu, location) {
  const days = Array.isArray(menu.days) ? menu.days : [];
  const floor = state.floorId;
  $("menu-floor").innerHTML = activeFloors().map(item =>
    `<option value="${item.id}"${item.id === floor ? " selected" : ""}>${item.id}층 ${escapeHtml(item.name)}</option>`
  ).join("");

  if (menuState.selectedLocation !== location.id || !days.some(day => day.date === menuState.selectedDate)) {
    const current = days.find(day => day.date === todayInSeoul());
    menuState.selectedDate = (current || days.find(day => day.entries?.length) || days[0])?.date || null;
  }
  menuState.selectedLocation = location.id;
  $("menu-date-tabs").innerHTML = days.map(day =>
    `<button type="button" data-menu-date="${escapeHtml(day.date)}" aria-pressed="${day.date === menuState.selectedDate}">${menuDateFormat.format(new Date(`${day.date}T00:00:00+09:00`))}</button>`
  ).join("");

  const entries = days.find(day => day.date === menuState.selectedDate)?.entries?.filter(entry => entry.floor === floor) || [];
  $("menu-content").innerHTML = entries.length
    ? `<div class="daily-menu-grid">${entries.map(menuEntryMarkup).join("")}</div>`
    : `<p class="menu-empty">선택한 날짜의 ${floor}층 메뉴가 등록되어 있지 않습니다. 공란은 휴무를 뜻하지 않습니다.</p>`;
}

function renderImageMenu(menu, location) {
  menuState.selectedLocation = location.id;
  const images = (menu.images || []).map(image => menuAsset(image.path)).filter(Boolean);
  const posters = images.map((path, index) =>
    `<a href="${path}" class="menu-image-link" target="_blank" rel="noopener noreferrer"><img src="${path}" alt="${escapeHtml(location.name)} ${escapeHtml(menu.periodStart)}부터 ${escapeHtml(menu.periodEnd)}까지 공식 식단표 ${index + 1}" loading="lazy"><span>원본 이미지 크게 보기 ↗</span></a>`
  ).join("");
  $("menu-content").innerHTML = `<p class="menu-original-note">학교에서 게시한 원본 식단표입니다. 이미지를 누르면 크게 볼 수 있습니다.</p><div class="menu-images${images.length > 1 ? " multiple" : ""}">${posters}</div>`;
}

function renderWeeklyMenus() {
  const location = activeLocation();
  const menu = menuState.catalog.locations?.[location.id];
  const availability = menuAvailability(menu);
  renderMenuHeader(location, menu, availability);

  if (!menu || availability.className === "unavailable") {
    $("menu-content").innerHTML = '<p class="menu-empty">등록된 식단 정보를 확인할 수 없습니다.</p>';
    return;
  }
  if (menu.format === "table") renderTableMenu(menu, location);
  else if (menu.format === "image") renderImageMenu(menu, location);
  else $("menu-content").innerHTML = '<p class="menu-empty">식단표 형식을 확인할 수 없습니다. 공식 안내를 확인해 주세요.</p>';

  $("menu-attachments").innerHTML = (menu.attachments || []).map(file => ({
    label: file.label, url: officialMenuUrl(file.url),
  })).filter(file => file.url).map(file =>
    `<a href="${escapeHtml(file.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(file.label)} ↗</a>`
  ).join("");
}

async function refreshWeeklyMenus(force = false) {
  if (!menuApiBase || menuState.refreshing) return;
  menuState.refreshing = true;
  renderWeeklyMenus();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 45000);
  try {
    const response = await fetch(`${menuApiBase}/menus${force ? "?refresh=true" : ""}`, { signal: controller.signal, cache: "no-store" });
    if (!response.ok) throw new Error("Menu request failed");
    const catalog = await response.json();
    if (catalog.version !== 1 || !catalog.locations || typeof catalog.locations !== "object") throw new Error("Invalid menu catalog");
    menuState.catalog = catalog;
    menuState.fetchFailed = false;
  } catch {
    menuState.fetchFailed = true;
  } finally {
    clearTimeout(timeout);
    menuState.refreshing = false;
    renderWeeklyMenus();
    if (force) $("announcement").textContent = menuState.fetchFailed ? "메뉴를 새로 확인하지 못했습니다. 저장된 자료를 표시합니다." : "공식 메뉴 확인을 마쳤습니다.";
  }
}

function initializeWeeklyMenus() {
  $("menu-floor").addEventListener("change", event => selectFloor(Number(event.target.value)));
  onClick("menu-date-tabs", "[data-menu-date]", button => {
    menuState.selectedDate = button.dataset.menuDate;
    renderWeeklyMenus();
    $("menu-date-tabs").querySelector(`[data-menu-date="${menuState.selectedDate}"]`)?.focus({ preventScroll: true });
  });
  $("menu-refresh").addEventListener("click", () => refreshWeeklyMenus(true));
  renderWeeklyMenus();
  refreshWeeklyMenus();
  setInterval(() => { if (!document.hidden) refreshWeeklyMenus(); }, 300000);
}
