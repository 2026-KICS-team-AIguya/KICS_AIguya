const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");

const root = path.resolve(__dirname, "..");
const python = process.env.PYTHON || (fs.existsSync(path.join(root, ".venv/Scripts/python.exe")) ? path.join(root, ".venv/Scripts/python.exe") : "python");
const kioskFixture = JSON.parse(execFileSync(python, ["-B", "-c", "import json; from server.kiosk_analysis import analyze_kiosk; print(json.dumps(analyze_kiosk(12)))"], { cwd: root, encoding: "utf8" }));
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length);

function element(id) {
  return { id, innerHTML: "", textContent: "", clientWidth: 600, clientHeight: 403,
    hidden: false, disabled: false, offsetWidth: 36, attributes: {}, handlers: {},
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
    sensor_scope: { location_id: "sangnok", floor: 2, link_id: "link_3", mode: "test" },
    floors: [{ floor: 1, status: "unconnected" }, { floor: 2, status, mode: "test", level: status === "ok" ? "혼잡" : null,
      confidence: status === "ok" ? .87 : null, timestamp: clock - 5000, progress: "12/24", history: [] },
      { floor: 3, status: "unconnected" }],
    kiosk: { status: "waiting", recent: null, previous: null, as_of: clock },
  });
  response = snapshot();
  for (const match of html.matchAll(/<script src="([^"]+)" defer><\/script>/g)) run(fs.readFileSync(path.join(root, "web", match[1]), "utf8"));
  return { run, nodes, intervals, calls, snapshot, setKiosk(value) { kioskResponse = value; }, failKiosk(value) { kioskFailure = value; }, setKioskFetch(value) { kioskFetch = value; }, setResponse(value) { response = value; }, fail(value) { failure = value; }, advance(ms) { clock += ms; },
    click(id, dataset) { nodes.get(id).handlers.click({ target: { closest: () => ({ dataset }) } }); } };
}

async function main() {
  const h = harness();
  await h.run("refreshDashboard()");
  const node = id => h.nodes.get(id);
  assert.equal(h.run("state.locations.length"), 3);
  assert.equal(h.run("state.floorId"), 2);
  assert.equal(node("floor-level").textContent, "—");
  assert.equal(node("kiosk-results").hidden, false); // CSI failure does not hide independent kiosk simulation.
  assert.ok(!node("floor-plan").innerHTML.includes("data-zone"));

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
  for (const floor of [1, 3, 2]) {
    h.click("floor-cards", { floor: String(floor) });
    assert.equal(h.run("state.floorId"), floor);
    if (floor !== 2) {
      assert.equal(node("floor-data-status").textContent, "예시 데이터");
      assert.equal(node("floor-confidence").textContent, "—");
    }
  }

  const synthetic = h.snapshot("ok");
  synthetic.floors[1].input_kind = "synthetic";
  h.setResponse(synthetic);
  await h.run("refreshDashboard()");
  assert.equal(node("floor-data-status").textContent, "예시 데이터");
  synthetic.floors[1].input_kind = "replay";
  await h.run("refreshDashboard()");
  assert.equal(node("floor-data-status").textContent, "기록 데이터");

  await h.run("refreshDashboard()");
  assert.equal(node("kiosk-recent").textContent, kioskFixture.surge_momentum.recent_5m);
  assert.equal(node("kiosk-results").hidden, false);
  assert.ok(node("kiosk-corners").innerHTML.includes("품절 예상"));
  assert.ok(node("kiosk-corners").innerHTML.includes("progress"));
  assert.ok(node("kiosk-sensor-source").textContent.includes("별도 자료"));
  for (const [label, query] of [["12:00", "test_hour=12&test_minute=0"], ["11:30", "test_hour=11&test_minute=30"], ["15:00", "test_hour=15&test_minute=0"], ["실시간", ""]]) {
    node("kiosk-mode").handlers.click();
    await h.run("refreshKiosk()");
    assert.ok(node("kiosk-mode-label").textContent.includes(label));
    assert.ok(h.calls.at(-1).endsWith(query || "/api/kiosk-analysis"));
  }
  h.failKiosk(true);
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-results").hidden, true);
  assert.equal(node("kiosk-retry").hidden, false);
  h.failKiosk(false);
  const malformed = structuredClone(kioskFixture);
  malformed.corners.special.remaining_stock = -1;
  h.setKiosk(malformed);
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-results").hidden, true);
  const sold = structuredClone(kioskFixture);
  sold.golden_time_stats.recommended_time = null;
  for (const c of Object.values(sold.corners)) { c.remaining_stock = 0; c.sold_out = true; }
  h.setKiosk(sold);
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-golden").textContent, "오늘 준비 수량 소진");
  h.setKiosk(kioskFixture);
  await h.run("refreshKiosk()");
  assert.equal(node("kiosk-results").hidden, false);
  // An older response must not overwrite a newer mode, even if abort is ignored.
  const pending = [];
  h.setKioskFetch(() => new Promise(resolve => pending.push(resolve)));
  const oldRequest = h.run("refreshKiosk()");
  h.run("kioskState.mode = 1");
  const newRequest = h.run("refreshKiosk()");
  const latest = structuredClone(kioskFixture); latest.summary_briefing = "new mode";
  pending[1]({ ok: true, json: async () => latest });
  await newRequest;
  pending[0]({ ok: true, json: async () => kioskFixture });
  await oldRequest;
  assert.equal(node("kiosk-briefing").textContent, "new mode");
  h.setKioskFetch(null);

  h.fail(true);
  await h.run("refreshDashboard()");
  assert.equal(node("floor-status").textContent, "연결 확인 중");
  assert.equal(node("floor-confidence").textContent, "—");
  assert.equal(node("kiosk-results").hidden, false); // CSI failure does not hide independent kiosk simulation.
  h.click("floor-tabs", { floor: "1" });
  assert.equal(node("floor-data-status").textContent, "예시 데이터");
  const calls = h.calls.length;
  node("auto-button").handlers.click();
  h.advance(60000);
  h.intervals.find(item => item.delay === 10000).callback();
  assert.equal(h.calls.length, calls);

  for (const location of ["dormitory", "business", "sangnok"]) {
    h.click("location-list", { location });
    assert.equal(h.run("state.locationId"), location);
    assert.equal(node("dining-content").hidden, location !== "sangnok");
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
