"use strict";

// Orthographic projection of simple 3D solids. No WebGL or network dependencies.
// Building positions and dimensions are intentionally schematic.
function drawCampus(locations, selectedId, angle, flat) {
  const stage = document.getElementById("campus-stage");
  const svg = document.getElementById("campus-scene");
  const pins = document.getElementById("campus-pins");
  const width = stage.clientWidth || 720;
  const height = stage.clientHeight || 430;
  const radians = angle * Math.PI / 180;
  const cos = Math.cos(radians);
  const sin = Math.sin(radians);
  const tilt = flat ? 1 : 0.57;
  const vertical = flat ? 0 : 0.82;

  function raw([x, y, z = 0]) {
    return [x * cos - y * sin, (x * sin + y * cos) * tilt - z * vertical];
  }

  const ground = [[-290, -230], [270, -230], [295, -180], [295, 210], [245, 240], [-290, 240]];
  const projectedBounds = ground.map(raw).concat(locations.map(location => {
    const g = location.geometry;
    return raw([g.x, g.y, g.height]);
  }));
  const xs = projectedBounds.map(point => point[0]);
  const ys = projectedBounds.map(point => point[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const margin = width < 500 ? 22 : 55;
  const scale = Math.min((width - margin * 2) / (maxX - minX), (height - 105) / (maxY - minY));
  function project(point) {
    const [x, y] = raw(point);
    return [width / 2 + (x - (minX + maxX) / 2) * scale,
      height / 2 + 20 + (y - (minY + maxY) / 2) * scale];
  }
  const pointString = points => points.map(point => project(point).map(value => value.toFixed(2)).join(",")).join(" ");
  function polygon(points, fill, extra = "") {
    return `<polygon points="${pointString(points)}" fill="${fill}" ${extra}/>`;
  }

  let markup = `<defs><pattern id="campus-grain" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="3" cy="3" r=".7" fill="#a4b398" opacity=".27"/></pattern></defs>`;
  if (!flat) markup += polygon(ground.map(([x, y]) => [x + 8, y + 8, -10]), "#b8ab88");
  markup += polygon(ground, "#e0d9b9");
  markup += polygon(ground, "url(#campus-grain)");
  // Paths and lawn patches are layout examples, not campus routes.
  markup += polygon([[-15, -230], [18, -230], [18, 240], [-15, 240]], "#f6ebd3");
  markup += polygon([[-290, -7], [295, -7], [295, 24], [-290, 24]], "#f6ebd3");
  markup += polygon([[-52, -36], [54, -36], [54, 53], [-52, 53]], "#eacda0");
  markup += polygon([[175, -195], [245, -195], [245, -70], [175, -70]], "#cbdcbf");

  const objects = locations.map(location => ({ kind: "building", location, x: location.geometry.x, y: location.geometry.y }));
  const treePositions = [[-260, -130], [-265, 10], [-230, 170], [-175, 210], [-40, -190], [30, -190], [240, -160], [245, -110], [230, 5], [245, 50], [65, 210], [-225, -195]];
  treePositions.forEach(([x, y]) => objects.push({ kind: "tree", x, y }));
  objects.sort((a, b) => (a.x * sin + a.y * cos) - (b.x * sin + b.y * cos));

  function building(location) {
    const g = location.geometry;
    const active = location.id === selectedId;
    const x0 = g.x - g.width / 2, x1 = g.x + g.width / 2;
    const y0 = g.y - g.depth / 2, y1 = g.y + g.depth / 2;
    const h = flat ? 0 : g.height;
    const roof = active ? "#c88257" : "#ead7b7";
    let result = `<g data-location="${location.id}" class="scene-building ${active ? "selected" : ""}">`;
    result += polygon([[x0 + 9, y0 + 10], [x1 + 14, y0 + 10], [x1 + 14, y1 + 17], [x0 + 9, y1 + 17]], "#52694b", 'opacity=".12"');
    if (!flat) {
      const frontY = cos >= 0 ? y1 : y0;
      const sideX = sin >= 0 ? x1 : x0;
      result += polygon([[x0, frontY, 0], [x1, frontY, 0], [x1, frontY, h], [x0, frontY, h]], active ? "#bd9468" : "#c1c9b9");
      result += polygon([[sideX, y0, 0], [sideX, y1, 0], [sideX, y1, h], [sideX, y0, h]], active ? "#d1a371" : "#d4d9ca");
      for (let z = 11; z < h - 8; z += 15) {
        for (let x = x0 + 9; x < x1 - 7; x += 16) {
          result += polygon([[x, frontY, z], [x + 8, frontY, z], [x + 8, frontY, z + 6], [x, frontY, z + 6]], active ? "#796f5d" : "#889782");
        }
        for (let y = y0 + 9; y < y1 - 7; y += 17) {
          result += polygon([[sideX, y, z], [sideX, y + 8, z], [sideX, y + 8, z + 6], [sideX, y, z + 6]], active ? "#988263" : "#a4af9c");
        }
      }
      for (let x = x0 + 3; x < x1 - 8; x += 12) {
        result += polygon([[x, frontY, 11], [x + 10, frontY, 11], [x + 10, frontY + (cos >= 0 ? 7 : -7), 8], [x, frontY + (cos >= 0 ? 7 : -7), 8]], Math.round((x - x0) / 12) % 2 ? "#f5e2b8" : "#a25338");
      }
    }
    result += polygon([[x0, y0, h], [x1, y0, h], [x1, y1, h], [x0, y1, h]], roof, `stroke="${active ? "#b98243" : "#c6cebc"}" stroke-width="1"`);
    result += polygon([[x0 + 6, y0 + 6, h + .5], [x1 - 6, y0 + 6, h + .5], [x1 - 6, y1 - 6, h + .5], [x0 + 6, y1 - 6, h + .5]], active ? "#dfa77c" : "#eee1c7");
    result += polygon([[g.x - 16, g.y - 12, h + 1], [g.x + 16, g.y - 12, h + 1], [g.x + 16, g.y + 5, h + 1], [g.x - 16, g.y + 5, h + 1]], active ? "#c3a783" : "#c3cbb9");
    return result + "</g>";
  }

  for (const object of objects) {
    if (object.kind === "building") markup += building(object.location);
    else {
      const bottom = project([object.x, object.y, 0]);
      const top = project([object.x, object.y, flat ? 0 : 24]);
      const radius = Math.max(3.2, 12 * scale);
      markup += `<line x1="${bottom[0]}" y1="${bottom[1]}" x2="${top[0]}" y2="${top[1]}" stroke="#7f8b6d" stroke-width="${2.5 * scale}"/><circle cx="${top[0]}" cy="${top[1]}" r="${radius}" fill="#8ca57e"/><circle cx="${top[0] - radius * .2}" cy="${top[1] - radius * .2}" r="${radius * .72}" fill="#a3bb92"/>`;
    }
  }
  // Decorative walkers are not measured people or tracked sensor locations.
  for (const [index, [x, y]] of [[0, [-8, 82]], [1, [54, 9]], [2, [-110, 7]]]) {
    const actor = project([x, y, 0]);
    const actorScale = Math.max(.45, scale);
    markup += `<g transform="translate(${actor[0]},${actor[1]}) scale(${actorScale})"><g class="campus-walker" style="animation-delay:${index * -1.6}s"><ellipse cy="2" rx="4" ry="2" fill="#7b6c53" opacity=".15"/><path d="M-2-2v-6m4 6v-6" stroke="#786449" stroke-width="2.5"/><rect x="-4" y="-17" width="8" height="10" rx="2" fill="${index % 2 ? "#75855c" : "#ab6647"}"/><circle cy="-21" r="3" fill="#c99d70"/><path d="M-3-22q1-5 6-1" stroke="#68533f" stroke-width="2"/></g></g>`;
  }

  // Native HTML buttons keep labels legible and keyboard/touch accessible.
  const labelWidth = width < 500 ? 90 : 106;
  const labels = locations.map(location => {
    const g = location.geometry;
    const anchor = project([g.x, g.y, flat ? 0 : g.height]);
    return { location, anchor, x: Math.max(labelWidth / 2 + 6, Math.min(width - labelWidth / 2 - 6, anchor[0])), y: Math.max(58, anchor[1] - 12) };
  }).sort((a, b) => a.y - b.y);
  for (let index = 0; index < labels.length; index++) {
    const current = labels[index];
    for (let previous = 0; previous < index; previous++) {
      const other = labels[previous];
      if (Math.abs(current.x - other.x) < labelWidth + 8 && Math.abs(current.y - other.y) < 57) current.y = other.y + 57;
    }
    current.y = Math.min(height - 35, current.y);
    markup += `<line x1="${current.anchor[0]}" y1="${current.anchor[1]}" x2="${current.x}" y2="${current.y}" stroke="#929d85" stroke-width="1"/>`;
  }
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.innerHTML = markup;
  const focusedId = document.activeElement?.closest?.("[data-location]")?.dataset.location;
  const restorePinFocus = pins.contains(document.activeElement);
  pins.innerHTML = labels.map(({ location, x, y }) => `<button type="button" class="campus-pin ${location.id === selectedId ? "selected" : ""}" data-location="${location.id}" aria-pressed="${location.id === selectedId}" aria-label="${location.name}, ${location.mode === "demo" ? "공식 메뉴와 더미 혼잡도 보기" : "공식 메뉴 보기, 혼잡도 준비 중"}" style="left:${x / width * 100}%;top:${y / height * 100}%"><span>${location.name}</span><small>${location.mode === "demo" ? "시연 중" : "준비 중"}</small></button>`).join("");
  if (restorePinFocus && focusedId) pins.querySelector(`[data-location="${focusedId}"]`)?.focus({ preventScroll: true });
}
