const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const python = process.env.PYTHON || (fs.existsSync(path.join(root, ".venv/Scripts/python.exe")) ? path.join(root, ".venv/Scripts/python.exe") : "python");
const kioskFixture = JSON.parse(execFileSync(python, ["-B", "-c", "import json; from server.kiosk_analysis import analyze_kiosk; print(json.dumps(analyze_kiosk(12)))"], { cwd: root, encoding: "utf8" }));
const liveKioskFixture = JSON.parse(execFileSync(python, ["-B", "-c", "import json; from datetime import datetime; from server.kiosk_analysis import analyze_kiosk, SEOUL; print(json.dumps(analyze_kiosk(now=datetime(2026,10,14,12,tzinfo=SEOUL))))"], { cwd: root, encoding: "utf8" }));
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length);
assert.match(html, /<details\b[^>]*id="weekly-menu"[^>]*>/);
assert.ok(!/<details\b[^>]*id="weekly-menu"[^>]*\bopen\b/.test(html));
assert.ok(!html.includes('id="kiosk-corners"'));
assert.ok(!html.includes("오늘의 세 코너"));
assert.ok(html.includes("식당 이용 추정"));

function element(id) {
  return { id, innerHTML: "", textContent: "", clientWidth: 600, clientHeight: 403,
    hidden: false, disabled: false, open: false, offsetWidth: 36, attributes: {}, handlers: {},
    style: { setProperty(key, value) { this[key] = value; } },
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(key, value) { this.attributes[key] = value; }, removeAttribute(key) { delete this.attributes[key]; },
    addEventListener(key, callback) { this.handlers[key] = callback; },
    contains() { return false; }, querySelectorAll() { return []; }, querySelector() { return null; }, animate() {},
    getBoundingClientRect() { return { left: 0, top: 0, width: 600, height: 400 }; },
  };
}

function harness({ lan = false } = {}) {
  let kioskResponse = structuredClone(kioskFixture), kioskFailure = false, kioskFetch;
  let clock = Date.UTC(2026, 9, 12, 4), response, failure = false;
  class TestDate extends Date {
    constructor(...args) { super(...(args.length ? args : [clock])); }
    static now() { return clock; }
  }
  class Observer { observe(target) { assert.ok(target); } unobserve() {} }
  const nodes = new Map(ids.map(id => [id, element(id)]));
  const intervals = [], calls = [];
  const context = vm.createContext({
    Date: TestDate, Intl, Math, URL, console, AbortController, setTimeout, clearTimeout,
    document: { getElementById: id => nodes.get(id), querySelector: () => element("receipt"), querySelectorAll: () => [], body: element("body"), activeElement: null, hidden: false },
    window: { location: { pathname: lan ? "/dashboard/" : "/", origin: lan ? "http://192.168.0.23:8000" : "http://localhost:5500" }, CONGESTION_API_BASE: lan ? undefined : "http://backend.example",
      matchMedia: () => ({ matches: true, addEventListener() {} }), IntersectionObserver: Observer, ResizeObserver: Observer, addEventListener() {} },
    IntersectionObserver: Observer, ResizeObserver: Observer,
    setInterval(callback, delay) { intervals.push({ callback, delay }); },
    async fetch(url) {
      calls.push(url);
      if (url.includes("kiosk-analysis") || url.includes("comprehensive-analysis")) {
        if (kioskFetch) return kioskFetch(url);
        if (kioskFailure) throw new Error("kiosk offline");
        return { ok: true, json: async () => kioskResponse };
      }
      if (failure) throw new Error("offline");
      return { ok: true, json: async () => response };
    },
  });
  const run = source => vm.runInContext(source, context);
  const snapshot = (status = "waiting") => ({
    version: 2, location_id: "sangnok", server_time: clock,
    sensor_scope: { location_id: "sangnok", floor: 1, link_id: "link_3", mode: "test" },
    floors: [{ floor: 1, status, mode: "test", level: status === "ok" ? "혼잡" : null,
      confidence: status === "ok" ? .87 : null, timestamp: clock - 5000, progress: "12/24", history: [] },
      { floor: 2, status: "unconnected" },
      { floor: 3, status: "unconnected" }],
    kiosk: { status: "waiting", recent: null, previous: null, as_of: clock },
  });
  response = snapshot();
  for (const match of html.matchAll(/<script src="([^"]+)" defer><\/script>/g)) run(fs.readFileSync(path.join(root, "web", match[1].split("?")[0]), "utf8"));
  return { run, nodes, intervals, calls, snapshot, setKiosk(value) { kioskResponse = value; }, failKiosk(value) { kioskFailure = value; }, setKioskFetch(value) { kioskFetch = value; }, setResponse(value) { response = value; }, fail(value) { failure = value; }, advance(ms) { clock += ms; },
    click(id, dataset) { nodes.get(id).handlers.click({ target: { closest: () => ({ dataset }) } }); } };
}

async function main() {
  const h = harness();
  await h.run("refreshDashboard()");
  const node = id => h.nodes.get(id);
  assert.equal(h.run("state.locations.length"), 3);
  assert.equal(h.run("state.floorId"), 1);
  assert.equal(node("weekly-menu").open, false);
  assert.equal(node("floor-level").textContent, "—");
  assert.equal(node("kiosk-results").hidden, false); // CSI failure does not hide independent kiosk simulation.
  assert.ok(!node("floor-plan").innerHTML.includes("data-zone"));

  // An old backend still assigned to floor 2 must not replace mock floors.
  const legacyScope = h.snapshot("waiting");
  legacyScope.sensor_scope.floor = 2;
  legacyScope.floors[0] = { floor: 1, status: "unconnected" };
  legacyScope.floors[1] = { floor: 2, status: "waiting" };
  h.setResponse(legacyScope);
  await h.run("refreshDashboard()");
  for (const floor of [2, 3]) {
    h.click("floor-cards", { floor: String(floor) });
    assert.equal(node("floor-data-status").textContent, "예시 데이터");
    assert.ok(["여유", "보통", "혼잡"].includes(node("floor-level").textContent));
    const card = node("floor-cards").innerHTML.match(new RegExp(`<button[^>]*data-floor="${floor}"[\\s\\S]*?<\\/button>`))[0];
    assert.ok(card.includes("예시 데이터"));
    assert.ok(!card.includes("측정 대기"));
    assert.ok(!card.includes("실시간 혼잡도"));
    assert.ok(node("trend-chart").innerHTML.includes("<svg"));
  }
  h.click("floor-tabs", { floor: "1" });
  assert.equal(node("floor-level").textContent, "—");

  for (const [status, label] of [["calibrating", "측정 준비 중"], ["skipped", "확인 중"], ["stale", "업데이트 지연"]]) {
    h.setResponse(h.snapshot(status));
    await h.run("refreshDashboard()");
    assert.equal(node("floor-status").textContent, label);
    assert.equal(node("floor-level").textContent, "—");
  }
  h.setResponse(h.snapshot("ok"));
  await h.run("refreshDashboard()");
  assert.equal(node("floor-level").textContent, "혼잡");
  assert.equal(node("floor-confidence").textContent, "87%");
  assert.equal(node("floor-data-status").textContent, "실시간 혼잡도");
  assert.ok(!node("floor-cards").innerHTML.includes("테스트"));
  assert.ok(!node("floor-cards").innerHTML.includes("점유율"));
  for (const floor of [2, 3, 1]) {
    const kioskCalls = h.calls.filter(url => url.includes("kiosk-analysis")).length;
    h.click("floor-cards", { floor: String(floor) });
    assert.equal(h.run("state.floorId"), floor);
    if (floor !== 1) {
      assert.equal(node("floor-data-status").textContent, "예시 데이터");
      assert.equal(node("floor-confidence").textContent, "—");
      assert.equal(node("kiosk-active-content").hidden, true);
      assert.equal(node("kiosk-pending").hidden, false);
      assert.ok(node("kiosk-pending-message").textContent.includes(`${floor}층`));
      assert.equal(node("kiosk-mode").hidden, true);
      await h.run("refreshKiosk()");
      assert.equal(h.calls.filter(url => url.includes("kiosk-analysis")).length, kioskCalls);
    } else {
      assert.equal(node("kiosk-active-content").hidden, false);
      assert.equal(node("kiosk-pending").hidden, true);
      assert.equal(node("kiosk-mode").hidden, false);
    }
  }

  const synthetic = h.snapshot("ok");
  synthetic.floors[0].input_kind = "synthetic";
  h.setResponse(synthetic);
  await h.run("refreshDashboard()");
  assert.equal(node("floor-data-status").textContent, "예시 데이터");
  synthetic.floors[0].input_kind = "replay";
  await h.run("refreshDashboard()");
  assert.equal(node("floor-data-status").textContent, "기록 데이터");

  await h.run("refreshDashboard()");
  assert.equal(node("kiosk-recent").textContent, kioskFixture.surge_momentum.recent_5m);
  assert.equal(node("kiosk-results").hidden, false);
  assert.ok(node("kiosk-sensor").textContent.startsWith("1층"));
  assert.ok(node("kiosk-sensor-source").textContent.includes("별도 자료"));
  h.setKiosk(liveKioskFixture);
  await h.run("refreshKiosk()");
  assert.ok(node("kiosk-asof").textContent.includes("목데이터"));
  assert.equal(node("kiosk-eating").textContent, liveKioskFixture.staying_estimation.current_eating);
  assert.ok(node("kiosk-eating").textContent > 0);
  assert.ok(node("kiosk-eating").textContent <= 120);
  assert.equal(node("kiosk-recent").textContent, liveKioskFixture.surge_momentum.recent_5m);
  h.setKiosk(kioskFixture);
  // Measured mode follows only fresh real CSI, without requesting random data.
  const measuredSnapshot = h.snapshot("ok");
  measuredSnapshot.floors[0].input_kind = "sensor";
  h.setResponse(measuredSnapshot);
  await h.run("refreshDashboard()");
  const callsBeforeMeasured = h.calls.length;
  node("kiosk-mode-measured").handlers.click();
  assert.equal(node("kiosk-results").hidden, false);
  assert.equal(node("kiosk-mode-measured").attributes["aria-pressed"], "true");
  assert.ok(node("kiosk-briefing").textContent.includes("혼잡"));
  assert.ok(node("kiosk-sensor-source").textContent.includes("혼잡도 기반 가상 추정"));
  assert.equal(h.calls.length, callsBeforeMeasured);
  h.fail(true);
  await h.run("refreshDashboard()");
  assert.equal(node("kiosk-results").hidden, true);
  assert.ok(node("kiosk-briefing").textContent.includes("기다리고"));
  h.fail(false);
  await h.run("refreshDashboard()");
  assert.equal(node("kiosk-results").hidden, false);
  node("kiosk-mode-random").handlers.click();
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-mode-random").attributes["aria-pressed"], "true");
  h.failKiosk(true);
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-results").hidden, true);
  assert.equal(node("kiosk-retry").hidden, false);
  h.failKiosk(false);
  const malformed = structuredClone(kioskFixture);
  malformed.staying_estimation.current_eating = 121;
  h.setKiosk(malformed);
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-results").hidden, true);
  const noRecommendation = structuredClone(liveKioskFixture);
  noRecommendation.golden_time_stats.recommended_time = null;
  delete noRecommendation.corners;
  h.setKiosk(noRecommendation);
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-results").hidden, false);
  assert.equal(node("kiosk-golden").textContent, "발권 흐름을 살펴보세요");
  h.setKiosk(kioskFixture);
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-results").hidden, false);
  // A late random response must not overwrite the selected measured mode.
  const pending = [];
  h.setKioskFetch(() => new Promise(resolve => pending.push(resolve)));
  const oldRequest = h.run("refreshKiosk()");
  node("kiosk-mode-measured").handlers.click();
  const measuredBriefing = node("kiosk-briefing").textContent;
  pending[0]({ ok: true, json: async () => kioskFixture });
  await oldRequest;
  assert.equal(node("kiosk-briefing").textContent, measuredBriefing);
  assert.equal(h.run("kioskState.payload.mode"), "measured");
  h.setKioskFetch(null);
  node("kiosk-mode-random").handlers.click();
  await h.run("refreshKiosk()");

  // Changing floors while a request is pending must hide its late result.
  h.setKioskFetch(() => new Promise(resolve => pending.push(resolve)));
  const floorRequest = h.run("refreshKiosk()");
  h.click("floor-tabs", { floor: "2" });
  pending.at(-1)({ ok: true, json: async () => kioskFixture });
  await floorRequest;
  assert.equal(node("kiosk-active-content").hidden, true);
  assert.equal(node("kiosk-pending").hidden, false);
  h.setKioskFetch(null);
  h.click("floor-tabs", { floor: "1" });
  await h.run("refreshKiosk()");

  node("weekly-menu").open = true;
  await h.run("refreshDashboard()");
  assert.equal(node("weekly-menu").open, true);

  h.fail(true);
  await h.run("refreshDashboard()");
  assert.equal(node("floor-status").textContent, "연결 확인 중");
  assert.equal(node("floor-confidence").textContent, "—");
  assert.equal(node("kiosk-results").hidden, false); // CSI failure does not hide independent kiosk simulation.
  h.click("floor-tabs", { floor: "2" });
  assert.equal(node("floor-data-status").textContent, "예시 데이터");
  const calls = h.calls.length;
  node("auto-button").handlers.click();
  h.advance(60000);
  h.intervals.find(item => item.delay === 10000).callback();
  assert.equal(h.calls.length, calls);
  h.click("floor-tabs", { floor: "1" });

  for (const location of ["dormitory", "business", "sangnok"]) {
    h.click("location-list", { location });
    assert.equal(h.run("state.locationId"), location);
    assert.equal(node("dining-content").hidden, location !== "sangnok");
    assert.equal(node("floor-cards").hidden, location !== "sangnok");
    assert.equal(node("kiosk-service").hidden, location !== "sangnok");
    if (location === "business") assert.equal(node("building-title").textContent, "D-plex");
  }
  node("view-flat").handlers.click();
  assert.equal(h.run("state.flat"), true);
  node("reset-view").handlers.click();
  assert.equal(h.run("state.flat"), false);
  assert.equal(h.run('officialMenuUrl("javascript:alert(1)")'), null);
  assert.equal(h.run('menuAsset("assets/menus/../../secret.png")'), null);
  h.run('menuState.catalog.locations.sangnok.days = [{date:"2026-10-12", entries:[]}]');
  h.click("menu-date-tabs", { menuDate: "2026-10-12" });
  assert.ok(node("menu-content").innerHTML.includes("menu-empty"));
  await new Promise(resolve => setImmediate(resolve));
  const lan = harness({ lan: true });
  await lan.run("refreshDashboard()");
  assert.ok(lan.calls.includes("http://192.168.0.23:8000/congestion?location_id=sangnok"));
  assert.ok(lan.calls.includes("http://192.168.0.23:8000/kiosk/comprehensive-analysis"));
  assert.ok(!lan.calls.some(url => url.includes("127.0.0.1")));
  console.log("PASS: floor AI states, marked demo floors, kiosk modes/races/errors, offline/pause, navigation and menu checks.");
  console.log("Mock DOM verification; browser layout requires separate inspection.");
}
main().catch(error => { console.error(error); process.exitCode = 1; });
