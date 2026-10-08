const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(root, "web/index.html"), "utf8");
const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.equal(new Set(ids).size, ids.length);

function element(id) {
  return {
    id, innerHTML: "", textContent: "", clientWidth: 600, clientHeight: 403,
    hidden: false, disabled: false, offsetWidth: 36, attributes: {}, handlers: {},
    style: { setProperty(key, value) { this[key] = value; } },
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(key, value) { this.attributes[key] = value; },
    addEventListener(key, callback) { this.handlers[key] = callback; },
    contains() { return false; }, querySelectorAll() { return []; }, querySelector() { return null; },
    animate() {},
    getBoundingClientRect() { return { left: 0, top: 0, width: 600, height: 400 }; },
  };
}

let clock = Date.UTC(2026, 9, 8, 4);
class TestDate extends Date {
  constructor(...args) { super(...(args.length ? args : [clock])); }
  static now() { return clock; }
}
class Observer { observe(target) { assert.ok(target); } unobserve() {} }
const nodes = new Map(ids.map(id => [id, element(id)]));
const extras = new Map([".receipt-heading", ".zone-detail"].map(id => [id, element(id)]));
const intervals = [];
const context = vm.createContext({
  Date: TestDate, Intl, Math, URL, console,
  document: {
    getElementById: id => nodes.get(id), querySelector: selector => extras.get(selector),
    querySelectorAll: () => [], body: element("body"), activeElement: null, hidden: false,
  },
  window: {
    location: { pathname: "/", origin: "http://localhost:5500" },
    matchMedia: () => ({ matches: true, addEventListener() {} }),
    IntersectionObserver: Observer, ResizeObserver: Observer, addEventListener() {},
  },
  IntersectionObserver: Observer, ResizeObserver: Observer,
  setInterval(callback, delay) { intervals.push({ callback, delay }); },
});
const run = source => vm.runInContext(source, context);
for (const match of html.matchAll(/<script src="([^"]+)" defer><\/script>/g)) {
  run(fs.readFileSync(path.join(root, "web", match[1]), "utf8"));
}

const snapshots = {};
function capture(name) {
  snapshots[name] = Object.fromEntries([...nodes].map(([id, node]) => [id, {
    text: node.textContent,
    html: node.innerHTML.replace(/\s+/g, " ").replace(/>\s+</g, "><").trim(),
    hidden: node.hidden, disabled: node.disabled, attributes: node.attributes,
    className: node.className, href: node.href, width: node.style.width,
  }]));
  // Snapshot values must not change when the next scenario updates attributes.
  snapshots[name] = JSON.parse(JSON.stringify(snapshots[name]));
}
function click(id, dataset) {
  nodes.get(id).handlers.click({ target: { closest: () => ({ dataset }) } });
}

assert.equal(run("state.locations.length"), 3);
assert.equal(nodes.get("ticket-count").textContent, "42");
assert.equal(nodes.get("zone-occupancy").textContent, "42%");
capture("initial");

for (const floor of [1, 3, 2]) {
  click("floor-cards", { floor: String(floor) });
  assert.equal(run("state.floorId"), floor);
  assert.equal(nodes.get("ticket-count").textContent, "42");
  capture(`floor-${floor}`);
}
click("floor-plan", { zone: "C" });
assert.equal(run("state.zoneId"), "C");
capture("zone-c");
click("menu-date-tabs", { menuDate: "2026-10-05" });
assert.ok(nodes.get("menu-content").innerHTML.includes("menu-empty"));
capture("unpublished-menu");

for (const location of ["dormitory", "business", "sangnok"]) {
  click("location-list", { location });
  assert.equal(run("state.locationId"), location);
  assert.equal(nodes.get("demo-content").hidden, location !== "sangnok");
  capture(location);
}
nodes.get("view-flat").handlers.click();
assert.equal(run("state.flat"), true);
capture("flat");
nodes.get("reset-view").handlers.click();
capture("reset");

clock += 10000;
intervals.find(interval => interval.delay === 10000).callback();
capture("auto-refresh");
nodes.get("auto-button").handlers.click();
const lastUpdate = run("state.lastUpdated.getTime()");
clock += 60000;
intervals.find(interval => interval.delay === 10000).callback();
assert.equal(run("state.lastUpdated.getTime()"), lastUpdate);
capture("paused");
nodes.get("refresh-button").handlers.click();
capture("manual-refresh");

assert.equal(run('officialMenuUrl("javascript:alert(1)")'), null);
assert.equal(run('menuAsset("assets/menus/../../secret.png")'), null);
assert.equal(run('menuAvailability({status:"error"}).className'), "unavailable");

const [mode, filename] = process.argv.slice(2);
if (mode === "--record") fs.writeFileSync(filename, JSON.stringify(snapshots));
if (mode === "--compare") assert.deepEqual(snapshots, JSON.parse(fs.readFileSync(filename, "utf8")));
console.log(`PASS: ${Object.keys(snapshots).length} frontend scenarios${mode === "--compare" ? ", matching pre-refactor output" : ""}.`);
console.log("Mock DOM verification; this does not verify browser layout.");
