"use strict";

// Fictional restaurant cutaway; furniture and people are illustrative only.
function drawDiningRoom(floor, selectedZone, container) {
  const width = Math.max(240, container.clientWidth || 600);
  const height = width < 450 ? 280 : 350;
  const scale = Math.min((width - 28) / 570, (height - 52) / 368);
  const origin = [width / 2, 82 * scale + 22];
  const project = ([x, y, z = 0]) => [origin[0] + (x - y) * .86 * scale, origin[1] + ((x + y) * .44 - z) * scale];
  const points = vertices => vertices.map(vertex => project(vertex).map(value => value.toFixed(2)).join(",")).join(" ");
  const polygon = (vertices, fill, attributes = "") => `<polygon points="${points(vertices)}" fill="${fill}" ${attributes}/>`;
  function box(x, y, w, d, h, roof, front, side, base = 0) {
    return polygon([[x, y + d, base], [x + w, y + d, base], [x + w, y + d, base + h], [x, y + d, base + h]], front)
      + polygon([[x + w, y, base], [x + w, y + d, base], [x + w, y + d, base + h], [x + w, y, base + h]], side)
      + polygon([[x, y, base + h], [x + w, y, base + h], [x + w, y + d, base + h], [x, y + d, base + h]], roof);
  }
  const colors = { free: "#e4e7c9", moderate: "#f1e1b0", busy: "#edd0bc" };
  let svg = polygon([[0, 0, -8], [310, 0, -8], [310, 310, -8], [0, 310, -8]], "#c6ab82");
  svg += polygon([[0, 0], [310, 0], [310, 310], [0, 310]], "#f6ecd9");
  for (let x = 0; x < 310; x += 31) {
    for (let y = 0; y < 310; y += 31) {
      if ((x / 31 + y / 31) % 2 === 0) svg += polygon([[x, y], [x + 31, y], [x + 31, y + 31], [x, y + 31]], "#e9dbc0");
    }
  }
  svg += box(-7, 0, 7, 310, 77, "#ceb798", "#e5d5b8", "#eadfc7");
  svg += box(0, -7, 310, 7, 77, "#ceb798", "#f3e7cf", "#d8c5a8");
  for (let x = 20; x < 190; x += 52) {
    svg += polygon([[x, .1, 30], [x + 38, .1, 30], [x + 38, .1, 65], [x, .1, 65]], "#b6c7b1", 'stroke="#a38663" stroke-width="2"');
    svg += polygon([[x + 18, .2, 30], [x + 20, .2, 30], [x + 20, .2, 65], [x + 18, .2, 65]], "#e2ccac");
  }
  svg += box(195, 5, 101, 23, 32, "#f8e6bd", "#a34b35", "#cb7250");
  for (let x = 200; x < 290; x += 17) svg += polygon([[x, 28.1, 2], [x + 8, 28.1, 2], [x + 8, 28.1, 28], [x, 28.1, 28]], "#f3d898");
  const zones = [[9, 40], [164, 40], [9, 174], [164, 174]];
  floor.zones.forEach((zone, index) => {
    const [x, y] = zones[index];
    const status = level(zone.occupancy);
    svg += `<g class="room-zone" data-zone="${zone.id}">${polygon([[x, y, .3], [x + 135, y, .3], [x + 135, y + 118, .3], [x, y + 118, .3]], colors[status.className], `opacity="${zone.id === selectedZone ? ".8" : ".38"}" stroke="${zone.id === selectedZone ? "#9e4430" : "#baae91"}" stroke-width="${zone.id === selectedZone ? "2" : ".6"}"`)}</g>`;
  });

  const furniture = [
    [32, 76, "A"], [101, 76, "A"], [187, 76, "B"], [256, 76, "B"],
    [32, 220, "C"], [101, 220, "C"], [187, 220, "D"], [256, 220, "D"],
  ];
  furniture.sort((a, b) => a[0] + a[1] - b[0] - b[1]);
  for (const [x, y, zone] of furniture) {
    let group = box(x, y, 31, 37, 3, "#a6784d", "#80593e", "#8f6743", 21);
    group += box(x + 2, y + 2, 3, 3, 21, "#835f42", "#835f42", "#835f42");
    group += box(x + 26, y + 30, 3, 3, 21, "#835f42", "#835f42", "#835f42");
    group += box(x - 12, y + 11, 8, 16, 13, "#b89b71", "#95744f", "#a98a62");
    group += box(x + 35, y + 11, 8, 16, 13, "#b89b71", "#95744f", "#a98a62");
    const plate = project([x + 15, y + 18, 25]);
    group += `<ellipse cx="${plate[0]}" cy="${plate[1]}" rx="${5.5 * scale}" ry="${3.3 * scale}" fill="#fcf1db"/><ellipse cx="${plate[0]}" cy="${plate[1]}" rx="${3.1 * scale}" ry="${1.8 * scale}" fill="#cc7950"/>`;
    svg += `<g class="room-zone-furniture" data-zone="${zone}">${group}</g>`;
    if (x === 32 || x === 187) {
      const person = project([x + 39, y + 20, 16]);
      svg += `<g transform="translate(${person[0]},${person[1]}) scale(${scale})"><g class="diner-sway" style="animation-delay:${(x + y) % 5 * -.7}s"><path d="M-4 4v9m8-9v9" stroke="#685847" stroke-width="4"/><rect x="-7" y="-12" width="14" height="18" rx="4" fill="${x === 32 ? "#9c553f" : "#7d9170"}"/><circle cy="-19" r="6" fill="#d6a978"/><path d="M-6-21q1-10 12-2v3H-6" fill="#65513d"/><path d="M-7-6l-7 5" stroke="#d6a978" stroke-width="4" stroke-linecap="round"/></g></g>`;
    }
    if (x === 101 && y === 76) {
      const steam = project([x + 15, y + 18, 27]);
      svg += `<g transform="translate(${steam[0]},${steam[1]}) scale(${scale})" class="room-steam"><path d="M-4 0q-5-5 0-10t0-10 M4 0q-5-5 0-10t0-10" fill="none" stroke="#a48e70" stroke-width="1.5"/></g>`;
    }
  }
  for (const [x, y] of [[12, 24], [17, 285], [289, 24]]) {
    const pot = project([x, y, 8]);
    svg += `<ellipse cx="${pot[0]}" cy="${pot[1]}" rx="${6 * scale}" ry="${4 * scale}" fill="#ae7452"/><path d="M${pot[0]} ${pot[1]}v${-19 * scale}" stroke="#6f8453" stroke-width="${2 * scale}"/>`;
    for (const [dx, dy] of [[-5, -15], [4, -20], [-1, -26]]) svg += `<ellipse cx="${pot[0] + dx * scale}" cy="${pot[1] + dy * scale}" rx="${6 * scale}" ry="${3.5 * scale}" fill="#849869"/>`;
  }
  floor.zones.forEach((zone, index) => {
    const [x, y] = zones[index];
    const label = project([x + 65, y + 112, 1]);
    svg += `<text x="${label[0]}" y="${label[1]}" text-anchor="middle" class="room-letter" fill="#856847">${zone.id}</text>`;
  });

  container.innerHTML = `<svg class="dining-room-scene" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" aria-hidden="true">${svg}</svg><div class="room-zone-buttons">${floor.zones.map(zone => {
    const status = level(zone.occupancy);
    return `<button type="button" class="zone-button ${status.className}" data-zone="${zone.id}" aria-pressed="${zone.id === selectedZone}" aria-label="${zone.id}구역 ${status.name}, 점유율 ${zone.occupancy}%"><span>${zone.id}구역</span><strong>${zone.occupancy}%</strong><small>${status.name}</small></button>`;
  }).join("")}</div>`;
}
