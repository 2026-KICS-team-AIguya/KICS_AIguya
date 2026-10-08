"use strict";

const $ = id => document.getElementById(id);

function dateFormatter(options, locale = "ko-KR") {
  return new Intl.DateTimeFormat(locale, { timeZone: "Asia/Seoul", ...options });
}

function escapeHtml(value) {
  const entities = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(value ?? "").replace(/[&<>"']/g, char => entities[char]);
}

function onClick(id, selector, action) {
  $(id).addEventListener("click", event => {
    const target = event.target.closest(selector);
    if (target) action(target, event);
  });
}
