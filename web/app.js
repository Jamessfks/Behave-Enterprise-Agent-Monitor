"use strict";
/* Agent Monitor front end: the live workspace app on the left, the workflow canvas and the
   monitor on the right. The server runs the agent one step at a time (POST /api/runs/current/next)
   and checks every step before it executes; this file only draws what comes back.

   Sections: utilities · api (+ fixture mode) · state · boot · app pane · canvas (pan/zoom/follow)
   · chain · monitor · pause card · run loop · summary · drawers. */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");
const reduced = () => motionQuery.matches;
const stepMs = () => (reduced() ? 250 : 650);
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage blocked: keep defaults */ } },
};

/* ---------- api ---------- */
/* Assets are relative (the canvas is served under /monitor/); API calls and app pages are absolute. */
const FIXTURE = new URLSearchParams(location.search).has("fixture");

async function api(path, body) {
  if (FIXTURE) return fixtureApi(path, body);
  const init = body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, init);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `${r.status} ${r.statusText}`);
  return j;
}

/* Fixture mode (/?fixture=1): canned responses from fixtures/*.json, so the UI runs without the
   server. A change marked `_needs: <approval id>` only appears once that approval is allowed. */
const FX = { files: {}, run: null, i: 0, approvals: {}, learned: [] };
const fxFile = async (name) => (FX.files[name] ??= await fetch(`fixtures/${name}`).then((r) => r.json()));
async function fixtureApi(path, body) {
  await sleep(90);
  if (path === "/api/bootstrap") return fxFile("bootstrap.json");
  if (path === "/api/rules") return { ...(await fxFile("rules.json")), learned: FX.learned };
  if (path === "/api/admin/reset") { FX.run = null; FX.approvals = {}; return { ok: true }; }
  if (path === "/api/runs/current") return { run: null, steps: [], changed: [], done: true };
  if (path === "/api/runs") {
    if (body.instruction) throw new Error("Live mode needs the server; fixture mode only replays the demo task.");
    FX.run = await fxFile(body.mistakes ? "run_mistakes.json" : "run_careful.json");
    FX.i = 0;
    FX.approvals = {};
    return { run: FX.run.run, steps_total: FX.run.steps_total };
  }
  if (path === "/api/runs/current/next") {
    const r = structuredClone(FX.run.next[Math.min(FX.i++, FX.run.next.length - 1)]);
    r.changed = r.changed.filter((c) => !c._needs || FX.approvals[c._needs] === "approved");
    return r;
  }
  const m = path.match(/^\/api\/approvals\/([^/]+)\/(approve|reject)$/);
  if (m) {
    FX.approvals[m[1]] = m[2] === "approve" ? "approved" : "rejected";
    const step = FX.run?.next.find((n) => n.step?.approval_id === m[1])?.step;
    if (m[2] === "approve") FX.learned.push({ id: `lr_${m[1]}`, reason: body.reason, decision: "allow", catalog_action: step?.catalog_action ?? "" });
    return { ok: true, id: m[1], status: FX.approvals[m[1]] };
  }
  throw new Error(`Fixture mode has no answer for ${path}.`);
}
const pageSrc = (url) => (FIXTURE ? `fixtures/app.html?u=${encodeURIComponent(url)}` : url);

/* ---------- glyphs and the electric edge ---------- */
const ICON = {
  Trigger: '<path d="M4 5h16v11H9l-5 4z M8 9h8 M8 12h5"/>',
  Jmail: '<path d="M4 6h16v12H4z M4 7l8 6 8-6"/>',
  Jdrive: '<path d="M7 3h7l4 4v14H7z M14 3v4h4 M10 12h5 M10 16h5"/>',
  Habspot: '<path d="M4 20V8l8-4 8 4v12 M9 20v-6h6v6 M4 20h16"/>',
  Quotes: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z M9 8h6 M9 12h6"/>',
  Calendario: '<path d="M4 6h16v14H4z M4 10h16 M8 3v4 M16 3v4"/>',
  Pending: '<path d="M6 12h.01 M12 12h.01 M18 12h.01"/>',
};
const glyph = (app) =>
  `<span class="glyph" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round">${ICON[app] || ICON.Habspot}</svg></span>`;

const EDGE = `<svg viewBox="0 0 40 56" aria-hidden="true">
  <line class="base" x1="20" y1="0" x2="20" y2="46"/>
  <line class="current" x1="20" y1="0" x2="20" y2="46"/>
  <path class="arc" d="M20 4 l-9 8 l13 7 l-11 9 l10 8 l-5 7"/>
  <circle class="spark" cx="20" cy="3" r="2.6"/>
  <path class="head" d="M14 45 L20 55 L26 45 Z"/></svg>`;

const CAUGHT_BY = { normal: "Step model", facts: "Fact check", rules: "Rules check" };
const RANKER_LABEL = { workflow: "Company workflow", behaviorgpt: "BehaviorGPT only", blend: "Blend" };
const KIND = { read: "reads", search: "searches", write: "changes something" };

/* ---------- state ---------- */
const S = {
  boot: null,
  mode: "demo",          // "demo" | "live"
  mistakes: true,
  busy: false,
  resumable: false,      // a run is in progress on the server (after a page reload)
  steps: [],             // [{ step, node, edge }]
  records: [],           // pauses, blocks and flags, for the summary
  changed: [],
  risks: [],
  latency: [],
  done: {},              // mistakes | careful | live -> { steps, records }
  appUrl: "",
};

/* ---------- boot ---------- */
async function init() {
  wireAppPane();
  wireCanvas();
  wireMonitor();
  try {
    S.boot = await api("/api/bootstrap");
  } catch (e) {
    $("#chain").innerHTML = `<li class="note status err">Couldn't reach the server: ${esc(e.message)}. Start it with <code>uv run uvicorn server:app</code>, or open this page with <code>?fixture=1</code>.</li>`;
    return;
  }
  const b = S.boot;
  $("#scenario-title").textContent = b.scenario.title;
  $("#scenario-dek").textContent = `${b.company.persona}'s AI agent at ${b.company.name} does the follow-up. Every step is checked before it runs.`;
  if (FIXTURE) $("#persona").textContent = "Fixture mode: canned responses, no server";
  rankerNote();
  wireControls();
  navigateApp(b.apps.mail);
  resetChain(true);
  fitHome(false);
  if (!FIXTURE) resume().catch(() => {});
}

function wireControls() {
  const segs = $$(".seg button");
  segs.forEach((b, i) => {
    b.addEventListener("click", () => pickMode(b.dataset.mode));
    b.addEventListener("keydown", (e) => {
      const d = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!d || S.busy) return;
      e.preventDefault();
      const next = segs[(i + d + segs.length) % segs.length];
      pickMode(next.dataset.mode);
      next.focus();
    });
  });
  $("#mistakes").addEventListener("click", () => {
    if (S.busy || S.mode === "live") return;
    S.mistakes = !S.mistakes;
    $("#mistakes").setAttribute("aria-checked", String(S.mistakes));
  });
  $("#run").addEventListener("click", () => (S.resumable ? continueRun() : startRun()));
  $("#reset").addEventListener("click", resetWorld);
  $("#setup").addEventListener("click", openSetup);
  $("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer" || e.target.closest("[data-close]")) closeDrawer(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden) closeDrawer(); });
}

function pickMode(mode) {
  if (S.busy) return;
  S.mode = mode;
  $$(".seg button").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.mode === mode));
    b.tabIndex = b.dataset.mode === mode ? 0 : -1;
  });
  const sw = $("#mistakes");
  sw.disabled = mode === "live";
  sw.title = mode === "live" ? "Mistakes are planted in the demo task only" : "";
  S.resumable = false;
  resetChain(true);
  fitHome(true);
}

function rankerNote() {
  const k = S.boot.default_ranker, r = S.boot.rankers?.[k];
  if (!r) return;
  const all = r.caught.length + r.missed.length;
  $("#ranker-note").textContent = k === "workflow"
    ? `Step model: ${RANKER_LABEL[k]}, learned from this company's approved runs. In calibration it caught ${r.caught.length} of ${all} behavior mistakes with ${r.false_alarms.length} false alarms. BehaviorGPT ranks every step too, as evidence only.`
    : `Step model: ${RANKER_LABEL[k] || k}. In calibration it caught ${r.caught.length} of ${all} behavior mistakes with ${r.false_alarms.length} false alarms.`;
}

function setBusy(on, label) {
  S.busy = on;
  const run = $("#run");
  run.disabled = on || (S.mode === "live" && !S.boot.live_available);
  run.textContent = on ? label : S.resumable ? "Continue the run" : S.steps.length ? "Run again" : "Run the agent";
  $("#reset").disabled = on;
  $("#mistakes").disabled = on || S.mode === "live";
  $$(".seg button").forEach((b) => (b.disabled = on));
}

/* ---------- app pane (left) ---------- */
const APP_OF = (url) => (url.startsWith("/mail") ? "mail" : url.startsWith("/drive") ? "drive" : url.startsWith("/crm") ? "crm" : url.startsWith("/calendar") ? "calendar" : "");

function navigateApp(url) {
  if (!url) return;
  S.appUrl = url;
  const src = pageSrc(url), f = $("#app-frame");
  if (f.dataset.src === src) {
    try { f.contentWindow.location.reload(); } catch { f.src = src; }
  } else {
    f.dataset.src = src;
    f.src = src;
  }
  $("#app-path").textContent = url;
  $("#app-open").href = src;
  const app = APP_OF(url);
  $$(".app-tabs button").forEach((b) => (b.dataset.app === app ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current")));
}
const reloadApp = () => navigateApp(S.appUrl);

function showAppPane(on) {
  document.body.classList.toggle("show-app", on);
  $("#show-app").setAttribute("aria-expanded", String(on));
  if (on) $("#app-close").focus();
  else $("#show-app").focus();
}

function wireAppPane() {
  $$(".app-tabs button").forEach((b) => b.addEventListener("click", () => S.boot && navigateApp(S.boot.apps[b.dataset.app])));
  $("#show-app").addEventListener("click", () => showAppPane(true));
  $("#app-close").addEventListener("click", () => showAppPane(false));
  // Resizable divider: drag or arrow keys; the split is remembered per browser.
  const split = $("#split"), div = $("#divider");
  const setLeft = (pct) => {
    pct = clamp(pct, 25, 75);
    split.style.setProperty("--left", `${pct}%`);
    div.setAttribute("aria-valuenow", String(Math.round(pct)));
    store.set("am.left", String(pct));
  };
  const saved = Number(store.get("am.left"));
  if (saved) setLeft(saved);
  div.addEventListener("pointerdown", (e) => {
    div.setPointerCapture(e.pointerId);
    document.body.classList.add("resizing");
    const move = (ev) => setLeft(((ev.clientX - split.getBoundingClientRect().left) / split.clientWidth) * 100);
    const up = () => {
      document.body.classList.remove("resizing");
      div.removeEventListener("pointermove", move);
      div.removeEventListener("pointerup", up);
      div.removeEventListener("pointercancel", up);
    };
    div.addEventListener("pointermove", move);
    div.addEventListener("pointerup", up);
    div.addEventListener("pointercancel", up);
  });
  div.addEventListener("keydown", (e) => {
    const d = { ArrowLeft: -2, ArrowRight: 2 }[e.key];
    if (!d) return;
    e.preventDefault();
    setLeft(Number(div.getAttribute("aria-valuenow")) + d);
  });
}

/* ---------- canvas: pan, zoom, follow ---------- */
const V = { x: 0, y: 0, s: 1, pref: 1, follow: true, anim: 0 };  // pref: the zoom the person chose
const MIN_Z = 0.15, MAX_Z = 2;

function applyView() {
  $("#world").style.transform = `translate(${V.x}px, ${V.y}px) scale(${V.s})`;
  const vp = $("#viewport").style;
  vp.setProperty("--gx", `${V.x}px`);
  vp.setProperty("--gy", `${V.y}px`);
  let g = 24 * V.s;
  while (g < 14) g *= 2; // zoomed far out: fewer, wider-spaced dots
  vp.setProperty("--gs", `${g}px`);
  $("#zoom-level").textContent = `${Math.round(V.s * 100)}%`;
}

function setView(x, y, s, animate = false) {
  cancelAnimationFrame(V.anim);
  if (!animate || reduced()) {
    Object.assign(V, { x, y, s });
    applyView();
    return;
  }
  const from = { x: V.x, y: V.y, s: V.s }, t0 = performance.now(), D = 460;
  const tick = (t) => {
    const k = Math.min(1, (t - t0) / D), e = 1 - Math.pow(1 - k, 3);
    V.x = from.x + (x - from.x) * e;
    V.y = from.y + (y - from.y) * e;
    V.s = from.s + (s - from.s) * e;
    applyView();
    if (k < 1) V.anim = requestAnimationFrame(tick);
  };
  V.anim = requestAnimationFrame(tick);
}

function zoomAt(factor, cx, cy) {
  const s = clamp(V.s * factor, MIN_Z, MAX_Z), k = s / V.s;
  V.pref = s;
  setView(cx - (cx - V.x) * k, cy - (cy - V.y) * k, s);
}
function zoomCenter(factor) {
  const vp = $("#viewport");
  zoomAt(factor, vp.clientWidth / 2, vp.clientHeight / 2);
}

/* World-space box of some elements (unaffected by the current pan and zoom). */
function worldBox(els) {
  const wr = $("#world").getBoundingClientRect();
  let top = Infinity, bottom = -Infinity, left = Infinity, right = -Infinity;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    top = Math.min(top, (r.top - wr.top) / V.s);
    bottom = Math.max(bottom, (r.bottom - wr.top) / V.s);
    left = Math.min(left, (r.left - wr.left) / V.s);
    right = Math.max(right, (r.right - wr.left) / V.s);
  }
  return { top, bottom, left, right };
}

/* Bring elements into view at the zoom the person chose. With `shrink` (a pause card), zoom out a
   little if they don't fit (not below 90%), then keep their bottom (the buttons) in view. */
function focusOn(els, animate = true, { shrink = false } = {}) {
  els = [els].flat().filter(Boolean);
  if (!els.length) return;
  const vp = $("#viewport"), vw = vp.clientWidth, vh = vp.clientHeight;
  const top = 20, bottom = vh - 20, room = Math.max(120, bottom - top);
  const b = worldBox(els), h = b.bottom - b.top;
  const s = shrink ? clamp(room / h, Math.min(V.pref, 0.9), V.pref) : V.pref;
  const x = vw / 2 - ((b.left + b.right) / 2) * s;
  const y = h * s <= room ? top + (room - h * s) / 2 - b.top * s : shrink ? bottom - b.bottom * s : top - b.top * s;
  setView(x, y, s, animate);
}
const follow = (els, animate = true, opts) => { if (V.follow) focusOn(els, animate, opts); };

function fitAll(animate = true) {
  const vp = $("#viewport"), w = $("#world");
  const vw = vp.clientWidth, vh = vp.clientHeight, ww = w.offsetWidth, wh = w.offsetHeight;
  const s = clamp(Math.min((vw - 40) / ww, (vh - 40) / wh), MIN_Z, 1);
  V.pref = s;
  setView((vw - ww * s) / 2, Math.max(20, (vh - wh * s) / 2), s, animate);
}
function fitHome(animate) {
  const vp = $("#viewport"), w = $("#world");
  V.pref = 1;
  setView((vp.clientWidth - w.offsetWidth) / 2, 24, 1, animate);
}

function setFollow(on) {
  V.follow = on;
  $("#follow").setAttribute("aria-pressed", String(on));
  store.set("am.follow", on ? "1" : "0");
  if (on) follow(currentFocus(), true, { shrink: !!$(".pause-card") });
}
const currentFocus = () => {
  const last = S.steps.at(-1);
  if (!$("#summary").hidden) return $("#summary");
  const card = $(".pause-card");
  return card ? [card.previousElementSibling, card] : last?.node;
};

function sizeNodes() {
  const vw = $("#viewport").clientWidth;
  $("#world").style.setProperty("--node-w", `${clamp(vw - 40, 290, 600)}px`);
}

function wireCanvas() {
  const vp = $("#viewport");
  sizeNodes();
  applyView();
  if (store.get("am.follow") === "0") setFollow(false);
  vp.addEventListener("scroll", () => { vp.scrollTop = 0; vp.scrollLeft = 0; }); // focus() must not scroll the canvas
  // Tabbing to something off-screen on the canvas pans to it.
  $("#world").addEventListener("focusin", (e) => {
    if (e.target.classList.contains("pause-card")) return; // the pause card places itself
    const r = e.target.getBoundingClientRect(), v = vp.getBoundingClientRect();
    if (r.top < v.top || r.bottom > v.bottom || r.left < v.left || r.right > v.right) {
      focusOn(e.target.closest(".node, .pause-card, .summary") || e.target, !reduced());
    }
  });
  new ResizeObserver(() => { sizeNodes(); if (S.steps.length) follow(currentFocus(), false, { shrink: !!$(".pause-card") }); }).observe(vp);

  $("#zoom-in").addEventListener("click", () => zoomCenter(1.2));
  $("#zoom-out").addEventListener("click", () => zoomCenter(1 / 1.2));
  $("#fit").addEventListener("click", () => fitAll(true));
  $("#follow").addEventListener("click", () => setFollow(!V.follow));

  // Ctrl/⌘ + wheel (and trackpad pinch) zooms at the pointer; a plain wheel pans.
  vp.addEventListener("wheel", (e) => {
    if (e.target.closest("textarea")) return;
    e.preventDefault();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? vp.clientHeight : 1;
    const r = vp.getBoundingClientRect();
    if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * unit * 0.0025), e.clientX - r.left, e.clientY - r.top);
    else setView(V.x - e.deltaX * unit, V.y - e.deltaY * unit, V.s);
  }, { passive: false });

  // Drag to pan (mouse, pen or one finger); two fingers pinch-zoom. A drag never clicks a node.
  const pts = new Map();
  let drag = null, pinch = null, justDragged = false;
  const NO_PAN = "input, textarea, select, label, a, summary, .pause-card, .summary button, .live-input";
  vp.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    if (e.target.closest(NO_PAN)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) drag = { id: e.pointerId, x: e.clientX, y: e.clientY, vx: V.x, vy: V.y, on: false };
    if (pts.size === 2) {
      const [a, b] = [...pts.values()], r = vp.getBoundingClientRect();
      pinch = { d: Math.hypot(a.x - b.x, a.y - b.y), s: V.s, vx: V.x, vy: V.y, cx: (a.x + b.x) / 2 - r.left, cy: (a.y + b.y) / 2 - r.top };
      drag = null;
    }
  });
  vp.addEventListener("pointermove", (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pinch && pts.size === 2) {
      const [a, b] = [...pts.values()];
      const s = clamp(pinch.s * Math.hypot(a.x - b.x, a.y - b.y) / pinch.d, MIN_Z, MAX_Z), k = s / pinch.s;
      V.pref = s;
      setView(pinch.cx - (pinch.cx - pinch.vx) * k, pinch.cy - (pinch.cy - pinch.vy) * k, s);
      return;
    }
    if (!drag || drag.id !== e.pointerId) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (!drag.on && Math.hypot(dx, dy) > 4) {
      drag.on = true;
      vp.setPointerCapture(e.pointerId);
      vp.classList.add("dragging");
    }
    if (drag.on) setView(drag.vx + dx, drag.vy + dy, V.s);
  });
  const end = (e) => {
    if (!pts.delete(e.pointerId)) return;
    if (drag?.on) { justDragged = true; setTimeout(() => (justDragged = false), 0); }
    if (pts.size < 2) pinch = null;
    if (!pts.size) drag = null;
    vp.classList.remove("dragging");
  };
  vp.addEventListener("pointerup", end);
  vp.addEventListener("pointercancel", end);
  vp.addEventListener("click", (e) => { if (justDragged) { e.stopPropagation(); e.preventDefault(); } }, true);

  // Keyboard, when the canvas itself has focus: arrows pan, +/− zoom, 0 fits.
  vp.addEventListener("keydown", (e) => {
    if (e.target !== vp) return;
    const step = e.shiftKey ? 200 : 60;
    const pan = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
    if (pan) { e.preventDefault(); setView(V.x + pan[0], V.y + pan[1], V.s); return; }
    if (e.key === "+" || e.key === "=") { e.preventDefault(); zoomCenter(1.2); }
    else if (e.key === "-" || e.key === "_") { e.preventDefault(); zoomCenter(1 / 1.2); }
    else if (e.key === "0") { e.preventDefault(); fitAll(true); }
  });
}

/* ---------- chain ---------- */
function resetChain(idle) {
  S.steps = []; S.records = []; S.changed = []; S.risks = []; S.latency = [];
  $("#chain").innerHTML = "";
  $("#ledger").innerHTML = "";
  $("#summary").hidden = true;
  drawRisk();
  $("#risk-now").textContent = "Risk 0%";
  $("#latency").textContent = "";
  $("#chain").append(triggerNode());
  if (idle) {
    for (const [app, name] of [["Jdrive", "Read the call, the email and the RFP"], ["Habspot", "Update the deal in Habspot"], ["Quotes", "Prepare the quote and the recap"]]) {
      const e = document.createElement("li");
      e.className = "edge ghost";
      e.setAttribute("aria-hidden", "true");
      e.innerHTML = EDGE;
      const g = document.createElement("li");
      g.className = "node ghost-step";
      g.setAttribute("aria-hidden", "true");
      g.innerHTML = `${glyph(app)}<div class="head">${esc(app)}</div><div class="title">${esc(name)}</div>`;
      $("#chain").append(e, g);
    }
    $("#chain").insertAdjacentHTML("beforeend", `<li class="idle-hint">${S.mode === "live" ? "Write a request, then" : "Press"} <strong>Run the agent</strong> to watch each step get checked before it runs.</li>`);
  }
  setBusy(false);
}

function triggerNode() {
  const b = S.boot, li = document.createElement("li");
  li.className = "node trigger";
  if (S.mode === "live") {
    const note = b.live_available
      ? "A Claude agent works in the workspace apps. Every step it takes is checked before it runs."
      : "Live mode needs an Anthropic API key on the server (ANTHROPIC_API_KEY). The demo task runs without one.";
    li.innerHTML = `${glyph("Trigger")}<div class="head">Live request</div><label class="title" for="instruction">Ask the agent anything, the way a colleague would</label>
      <div class="live-input"><textarea id="instruction" rows="4" ${b.live_available ? "" : "disabled"} aria-describedby="live-note">${esc(b.scenario.request)}</textarea>
      <p id="live-note" class="note">${esc(note)}</p></div>`;
  } else {
    li.innerHTML = `${glyph("Trigger")}<div class="head">Trigger</div><div class="title">Request from ${esc(b.company.persona)}</div><div class="meta request">“${esc(b.scenario.request)}”</div>`;
  }
  return li;
}

function stepTitle(st) { return st.label || st.name || st.catalog_action || st.action; }

function metaLine(st) {
  const v = st.values || {};
  const parts = Object.entries(v).map(([k, x]) => `${k.replaceAll("_", " ")}: ${x}`);
  return parts.join("; ") || st.app;
}

function pendingStep() {
  const edge = document.createElement("li");
  edge.className = "edge running";
  edge.setAttribute("aria-hidden", "true");
  edge.innerHTML = EDGE;
  const node = document.createElement("li");
  node.className = "node running pending";
  node.innerHTML = `${glyph("Pending")}<div class="head">Step ${S.steps.length + 1}</div><div class="title">Checking the next step…</div><div class="checks"><span class="chip">checking</span></div>`;
  $("#chain").append(edge, node);
  follow(node);
  return { edge, node };
}

function fillStep(node, st) {
  node.classList.remove("pending");
  node.dataset.i = String(st.index);
  node.innerHTML = `${glyph(st.app)}<div class="head">${st.index + 1}. ${esc(st.app)} <span class="kind">${esc(KIND[st.kind] || st.kind || "")}</span></div>
    <div class="title">${esc(stepTitle(st))}</div><div class="meta">${esc(metaLine(st))}</div>
    <div class="checks">${chips(st)}</div>
    <button class="open" aria-label="Details for step ${st.index + 1}: ${esc(stepTitle(st))}"></button>`;
  node.querySelector(".open").addEventListener("click", () => openStep(st));
}

function chips(st) {
  const c = st.check?.checks || {}, out = [];
  if (c.normal?.status === "scored") out.push(c.normal.ok ? '<span class="chip ok">normal</span>' : '<span class="chip bad">unusual</span>');
  if (c.facts?.checked?.length) {
    out.push(!c.facts.ok ? '<span class="chip bad">unsupported</span>'
      : c.facts.warnings?.length ? '<span class="chip warn">sources disagree</span>' : '<span class="chip ok">facts</span>');
  }
  const irreversible = S.boot.catalog?.[st.catalog_action]?.irreversible;
  if (st.kind === "write" || c.rules?.violations?.length || c.rules?.precedents?.length || irreversible) {
    out.push(c.rules?.ok === false ? '<span class="chip bad">breaks rule</span>' : '<span class="chip ok">rules</span>');
  }
  const d = { pause: '<span class="chip state s-pause">paused</span>', flag: '<span class="chip state s-flag">flagged</span>', block: '<span class="chip state s-block">blocked</span>' }[st.decision];
  if (d) out.push(d);
  return out.join("") || '<span class="chip ok">passed</span>';
}

function settle(node, edge, st) {
  node.classList.remove("running");
  const meta = node.querySelector(".meta"), ck = st.check || {};
  if (ck.verdict === "allowed_by_rule" && ck.precedent) {
    node.classList.add("allowed");
    meta.textContent = `Allowed by your earlier rule: “${ck.precedent}”`;
  } else if (st.decision === "flag") {
    node.classList.add("flagged");
    meta.textContent = `${metaLine(st)}. Flagged: ${ck.headline || "worth a look"}. It ran.`;
  } else if (st.decision === "block") {
    node.classList.add("blocked");
    meta.textContent = `Blocked by a hard rule: ${ck.headline || ck.reasons?.[0] || "not allowed"}. It never ran.`;
  } else if (ck.checks?.facts?.warnings?.length) {
    meta.textContent = `${metaLine(st)}. ${ck.checks.facts.warnings[0]}`;
  }
  edge.className = "edge " + ({ pause: "paused", block: "blocked" }[st.decision] || "passed");
  if (st.decision === "pause") node.classList.add("paused");
  if (st.decision === "flag" || st.decision === "block") record(st, st.decision === "flag" ? "flagged" : "blocked_rule");
}

function record(st, decision, reason = "") {
  S.records.push({ step: st.index + 1, name: stepTitle(st), failed: st.check?.failed || [], decision, reason, pause: st.decision === "pause" });
}

/* ---------- monitor ---------- */
function wireMonitor() {
  const t = $("#monitor-toggle"), body = $("#monitor-body");
  const set = (open) => {
    body.hidden = !open;
    t.setAttribute("aria-expanded", String(open));
    t.textContent = open ? "Hide steps" : "All steps";
    store.set("am.monitor", open ? "1" : "0");
  };
  set(store.get("am.monitor") === "1");
  t.addEventListener("click", () => set(body.hidden));
}

function ledgerRow(st) {
  const n = st.check?.checks?.normal || {}, N = n.behaviorgpt?.of || Object.keys(S.boot.catalog).length;
  const flag = st.decision === "pause" || st.decision === "block";
  const li = document.createElement("li");
  li.className = "row" + (flag ? " flag" : "");
  let bar = "<span></span>", rank = st.kind === "search" ? "search" : "", more = "";
  if (n.status === "scored") {
    const exp = Math.max(0.04, (N - n.rank + 1) / N);
    bar = `<div class="bar-exp" role="img" aria-label="How expected: rank ${n.rank} of ${N}"><i style="width:${(exp * 100).toFixed(0)}%"></i></div>`;
    rank = `#${n.rank}`;
    const guess = (n.expected || []).slice(0, 2).map((x) => esc(x.name)).join("; ");
    const bg = n.behaviorgpt?.rank ? `BehaviorGPT, as evidence: ranked it #${n.behaviorgpt.rank} of ${n.behaviorgpt.of}; its top guess was ${esc(n.behaviorgpt.top?.[0]?.name ?? "n/a")}.` : "BehaviorGPT: not available for this step.";
    more = `<details${flag ? " open" : ""}><summary>${flag ? "Why it stopped" : "What was expected"}</summary><p>Expected next: ${guess || "n/a"}.</p><p>${bg}</p></details>`;
  }
  const label = { pause: "Paused: ", block: "Blocked: ", flag: "Flagged: " }[st.decision] || "";
  li.innerHTML = `<span class="n">${st.index + 1}</span><span class="what" title="${esc(stepTitle(st))}">${esc(label + stepTitle(st))}</span>${bar}<span class="rank">${rank}</span>${more}`;
  $("#ledger").prepend(li);
}

function drawRisk() {
  const svg = $("#risk-chart"), W = 300, H = 64, top = 1.8;
  const pts = S.risks;
  const y = (r) => H - Math.min(r, top) / top * (H - 6) - 3;
  const x = (i) => (pts.length < 2 ? 0 : (i / (pts.length - 1)) * W);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.risk).toFixed(1)}`).join(" ");
  svg.innerHTML = `<line class="baseline" x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}"/><line class="barrier" x1="0" x2="${W}" y1="${y(1)}" y2="${y(1)}"/>${line ? `<path class="line" d="${line}"/>` : ""}` +
    pts.map((p, i) => (p.flag ? `<line class="flag" x1="${x(i)}" x2="${x(i)}" y1="0" y2="${H}"/>` : "")).join("");
}

function track(st) {
  const ck = st.check || {}, n = ck.checks?.normal || {};
  S.risks.push({ risk: n.risk || 0, flag: st.decision === "pause" || st.decision === "block" });
  drawRisk();
  $("#risk-now").textContent = `Risk ${Math.round((n.risk || 0) * 100)}%`;
  if (ck.latency_ms) {
    S.latency.push(ck.latency_ms);
    const avg = (k) => (S.latency.reduce((a, l) => a + (l[k] || 0), 0) / S.latency.length).toFixed(1);
    $("#latency").textContent = `Check time per step, server side: step model ${avg("normal")} ms, facts ${avg("facts")} ms, rules ${avg("rules")} ms.`;
  }
}

/* ---------- pause card ---------- */
function pauseCard(node, st) {
  return new Promise((resolve) => {
    const ck = st.check || {}, i = st.index;
    const card = document.createElement("li");
    card.className = "pause-card";
    card.setAttribute("aria-labelledby", `pause-h-${i}`);
    card.tabIndex = -1;
    const people = (ck.checks?.rules?.violations || []).filter((v) => v.author);
    const by = (ck.failed || []).map((f) => CAUGHT_BY[f] || f).join(", ");
    card.innerHTML = `<h3 id="pause-h-${i}">Paused before it ran${by ? `<span class="by">Caught by: ${esc(by)}</span>` : ""}</h3>
      ${ck.headline ? `<p class="lede">${esc(ck.headline)}</p>` : ""}
      <ul>${(ck.reasons || []).filter((r) => r !== ck.headline).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${people.map((v) => `<blockquote class="quote"><p>${esc(v.text)}</p><footer>${esc(v.author)}, team know-how</footer></blockquote>`).join("")}
      <label for="why-${i}">Allow needs a reason, which becomes a rule. Block needs none.</label>
      <textarea id="why-${i}" rows="2" placeholder="For example: Alex confirmed this with Dana by phone"></textarea>
      <div class="actions"><button class="primary" data-allow disabled>Allow</button><button class="danger" data-block>Block</button><span class="status" role="status"></span></div>`;
    node.after(card);
    $("#run").textContent = "Waiting for you…";
    // While the run waits on a person, Reset world stays usable: it abandons this run.
    S.cancelPause = () => { card.remove(); S.cancelPause = null; resolve({ decision: "abandoned" }); };
    $("#reset").disabled = false;
    const why = card.querySelector("textarea"), allow = card.querySelector("[data-allow]"), status = card.querySelector(".status");
    why.addEventListener("input", () => { allow.disabled = !why.value.trim(); });
    const decide = async (decision) => {
      const reason = why.value.trim();
      if (decision === "allow" && !reason) return;
      const controls = card.querySelectorAll("button, textarea");
      controls.forEach((x) => (x.disabled = true));
      status.className = "status";
      status.textContent = decision === "allow" ? "Allowing…" : "Blocking…";
      try {
        await api(`/api/approvals/${encodeURIComponent(st.approval_id)}/${decision === "allow" ? "approve" : "reject"}`, { reason });
      } catch (e) {
        status.className = "status err";
        status.textContent = `Couldn't save the decision: ${e.message}`;
        controls.forEach((x) => (x.disabled = false));
        allow.disabled = !why.value.trim();
        return;
      }
      const viewport = $("#viewport");
      const hadFocus = card.contains(document.activeElement);
      card.remove();
      S.cancelPause = null;
      if (S.busy) { $("#run").textContent = "Running…"; $("#reset").disabled = true; }
      if (hadFocus) viewport.focus({ preventScroll: true });
      resolve({ decision, reason });
    };
    allow.addEventListener("click", () => decide("allow"));
    card.querySelector("[data-block]").addEventListener("click", () => decide("block"));
    requestAnimationFrame(() => {
      focusOn([node, card], true, { shrink: true }); // a pause always comes into view: the run waits on it
      card.focus({ preventScroll: true });
    });
  });
}

function decided(node, edge, st, d) {
  node.classList.remove("paused");
  node.classList.add(d.decision === "allow" ? "allowed" : "blocked");
  edge.className = "edge " + (d.decision === "allow" ? "passed" : "blocked");
  node.querySelector(".chip.state")?.replaceWith(Object.assign(document.createElement("span"), {
    className: `chip state ${d.decision === "allow" ? "s-allow" : "s-block"}`, textContent: d.decision === "allow" ? "allowed" : "blocked",
  }));
  node.querySelector(".meta").textContent = d.decision === "allow"
    ? `Allowed: “${d.reason}”. Saved as a rule.`
    : `Blocked. The step never ran.${d.reason ? ` Reason: “${d.reason}”.` : ""}`;
  record(st, d.decision, d.reason);
}

/* ---------- run loop ---------- */
async function startRun() {
  if (S.busy) return;
  const live = S.mode === "live";
  const instruction = live ? $("#instruction")?.value.trim() : "";
  if (live && !instruction) { $("#instruction")?.focus(); return; }
  const body = live ? { instruction } : { scenario: S.boot.scenario.id, mistakes: S.mistakes };
  resetChain(false);
  if (live) { const t = $("#instruction"); t.value = instruction; t.disabled = true; }
  setBusy(true, live ? "Agent working…" : "Running…");
  fitHome(true);
  try {
    const r = await api("/api/runs", body);
    S.run = { ...r.run, total: r.steps_total };
    navigateApp(S.boot.apps.mail);
    await loop();
  } catch (e) {
    $("#chain").insertAdjacentHTML("beforeend", `<li class="note status err">Stopped: ${esc(e.message)}</li>`);
  } finally {
    S.resumable = false;
    setBusy(false);
  }
}

async function continueRun() {
  S.resumable = false;
  setBusy(true, "Running…");
  try { await loop(); } catch (e) {
    $("#chain").insertAdjacentHTML("beforeend", `<li class="note status err">Stopped: ${esc(e.message)}</li>`);
  } finally { setBusy(false); }
}

async function loop() {
  for (let guard = 0; guard < 200; guard++) {
    const { edge, node } = pendingStep();
    let res;
    try {
      [res] = await Promise.all([api("/api/runs/current/next", {}), sleep(stepMs())]);
    } catch (e) {
      edge.remove(); node.remove();
      throw e;
    }
    if (Array.isArray(res.changed)) S.changed = res.changed;
    if (res.done || !res.step) { edge.remove(); node.remove(); break; }
    await showStep(res.step, edge, node, true);
    if (S.abandoned) return;
  }
  finish();
}

/* Draw one step; for a live pause, wait for the person's decision. */
async function showStep(st, edge, node, live) {
  fillStep(node, st);
  settle(node, edge, st);
  S.steps.push({ step: st, node, edge });
  ledgerRow(st);
  track(st);
  if (st.page) navigateApp(st.page);
  follow(node);
  if (st.decision === "pause" && live) {
    const d = await pauseCard(node, st);
    if (d.decision === "abandoned") return;
    decided(node, edge, st, d);
    reloadApp();
    follow(node);
  }
}

/* After a page reload: redraw the server's current run, and pick up a pending pause. */
async function resume() {
  const cur = await api("/api/runs/current");
  if (!cur?.run || !cur.steps?.length) return;
  S.mode = cur.run.live ? "live" : "demo";
  S.mistakes = !!cur.run.mistakes;
  $("#mistakes").setAttribute("aria-checked", String(S.mistakes));
  $$(".seg button").forEach((b) => { b.setAttribute("aria-checked", String(b.dataset.mode === S.mode)); b.tabIndex = b.dataset.mode === S.mode ? 0 : -1; });
  resetChain(false);
  S.changed = cur.changed || [];
  const last = cur.steps.length - 1;
  for (const [k, st] of cur.steps.entries()) {
    const edge = document.createElement("li"), node = document.createElement("li");
    edge.setAttribute("aria-hidden", "true");
    edge.innerHTML = EDGE;
    node.className = "node";
    $("#chain").append(edge, node);
    const pendingPause = !cur.done && k === last && st.decision === "pause";
    await showStep(st, edge, node, false);
    if (st.decision === "pause" && !pendingPause) {
      const res = st.resolution || st.approval || {};
      const dec = res.decision || (res.status === "approved" ? "allow" : res.status === "rejected" ? "block" : "");
      if (dec) decided(node, edge, st, { decision: dec === "allow" ? "allow" : "block", reason: res.reason || "" });
      else { node.querySelector(".meta").textContent = "Paused; decided before this page was reloaded."; record(st, "decided"); }
    }
    if (pendingPause) {
      setBusy(true, "Waiting for you…");
      const d = await pauseCard(node, st);
      if (d.decision === "abandoned") { setBusy(false); return; }
      decided(node, edge, st, d);
      reloadApp();
      S.resumable = true;
      setBusy(false);
    }
  }
  if (cur.done) finish();
  else { S.resumable = true; setBusy(false); }
}

async function resetWorld() {
  if (S.busy && !S.cancelPause) return;
  if (S.cancelPause) { S.abandoned = true; S.cancelPause(); }
  $("#reset").disabled = true;
  try {
    await api("/api/admin/reset", {});
    S.resumable = false;
    resetChain(true);
    fitHome(true);
    navigateApp(S.boot.apps.mail);
  } catch (e) {
    $("#chain").insertAdjacentHTML("beforeend", `<li class="note status err">Reset failed: ${esc(e.message)}</li>`);
  } finally {
    S.abandoned = false;
    setBusy(false);
    $("#reset").disabled = false;
  }
}

/* ---------- summary ---------- */
const DECISION_TEXT = {
  allow: (r) => `Allowed: “${r.reason}”`,
  block: (r) => (r.reason ? `Blocked: “${r.reason}”` : "Blocked"),
  blocked_rule: () => "Blocked by a hard rule",
  flagged: () => "Flagged; it ran",
  decided: () => "Decided earlier",
};

function finish() {
  const key = S.mode === "live" ? "live" : S.mistakes ? "mistakes" : "careful";
  S.done[key] = { steps: S.steps.length, records: S.records.slice() };
  const pauses = S.records.filter((r) => r.pause);
  const box = $("#summary");
  let html = `<h3 class="display">${pauses.length ? `${pauses.length} step${pauses.length > 1 ? "s" : ""} paused for a person` : "No step needed a person"}</h3>
    <p class="dek">${S.steps.length} steps, each checked before it ran.${pauses.length ? ` ${pauses.filter((p) => p.decision === "allow").length} allowed with a reason, ${pauses.filter((p) => p.decision === "block").length} blocked.` : ""}</p>`;
  if (S.records.length) {
    html += `<div class="table-wrap"><table class="compare caught"><thead><tr><th>Step</th><th>Action</th><th>Caught by</th><th>Decision</th></tr></thead><tbody>${S.records.map((r) =>
      `<tr><td data-label="Step">${r.step}</td><td data-label="Action">${esc(r.name)}</td><td data-label="Caught by">${esc(r.failed.map((f) => CAUGHT_BY[f] || f).join(", ") || "Rules check")}</td><td data-label="Decision" class="dec-${esc(r.decision)}">${esc((DECISION_TEXT[r.decision] || (() => r.decision))(r))}</td></tr>`).join("")}</tbody></table></div>`;
  }
  const m = S.done.mistakes, c = S.done.careful;
  if (m && c) {
    const caught = (x) => x.records.filter((y) => y.pause).map((y) => y.name).join("; ") || "nothing";
    html += `<h4>With and without mistakes, same task</h4><div class="table-wrap"><table class="compare side"><thead><tr><th></th><th>No mistakes</th><th>Planted mistakes</th></tr></thead><tbody>
      <tr><th>Steps</th><td>${c.steps}</td><td>${m.steps}</td></tr>
      <tr><th>Paused</th><td>${c.records.filter((r) => r.pause).length}</td><td>${m.records.filter((r) => r.pause).length}</td></tr>
      <tr><th>Flagged</th><td>${c.records.filter((r) => r.decision === "flagged").length}</td><td>${m.records.filter((r) => r.decision === "flagged").length}</td></tr>
      <tr><th>What was caught</th><td>${esc(caught(c))}</td><td>${esc(caught(m))}</td></tr></tbody></table></div>`;
  } else if (key !== "live") {
    html += `<p class="note">Turn Plant mistakes ${S.mistakes ? "off" : "on"} and run again to compare both runs side by side.</p>`;
  }
  const changed = (S.changed || []);
  html += `<h4>What changed</h4>` + (changed.length
    ? `<ul class="changed">${changed.map((c) => `<li><button class="linkish" data-url="${esc(c.url)}"><span class="app-name">${esc(c.app)}</span><span class="lbl">${esc(c.label)}</span></button></li>`).join("")}</ul>`
    : '<p class="note">Nothing in the workspace changed.</p>');
  box.innerHTML = html;
  box.hidden = false;
  box.querySelectorAll("[data-url]").forEach((b) => b.addEventListener("click", () => {
    navigateApp(b.dataset.url);
    if (matchMedia("(max-width: 900px)").matches) showAppPane(true);
  }));
  requestAnimationFrame(() => follow(box));
}

/* ---------- drawers ---------- */
let lastFocus = null;
function openDrawer(titleText, html) {
  lastFocus = document.activeElement;
  $("#drawer-title").textContent = titleText;
  $("#drawer-body").innerHTML = html;
  $("#drawer").hidden = false;
  $("#drawer .close").focus();
}
function closeDrawer() {
  $("#drawer").hidden = true;
  lastFocus?.focus();
}

function highlight(text, needles) {
  let out = esc(text);
  for (const s of needles) if (s) out = out.split(esc(s)).join(`<mark>${esc(s)}</mark>`);
  return out;
}

function openStep(st) {
  const ck = st.check || {}, c = ck.checks || {}, n = c.normal || {}, f = c.facts || { checked: [], warnings: [] }, r = c.rules || { violations: [], precedents: [] };
  let html = "";
  if (ck.headline || ck.reasons?.length) {
    const h = { pause: "Why it paused", flag: "Why it was flagged", block: "Why it was blocked" }[st.decision] || "Notes";
    html += `<section><h3>${h}</h3>${ck.headline ? `<p><strong>${esc(ck.headline)}</strong></p>` : ""}<ul>${(ck.reasons || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul></section>`;
  }
  if (st.values && Object.keys(st.values).length) html += `<section><h3>What the agent did</h3><dl class="kv">${Object.entries(st.values).map(([k, v]) => `<dt>${esc(k.replaceAll("_", " "))}</dt><dd>${esc(v)}</dd>`).join("")}</dl></section>`;
  if (st.page) html += `<section><button class="ghost" id="open-page">Show this page in ${esc(st.app)}</button></section>`;
  if (f.checked?.length) {
    html += `<section><h3>Fact check</h3>${f.checked.map((x) => `<p><strong>${esc(String(x.field).replaceAll("_", " "))} = ${esc(x.value)}</strong>: ${x.ok ? "found in the sources" : "not supported"}${x.expected ? ` (expected ${esc([x.expected].flat().join(" or "))})` : ""}</p>` +
      (x.evidence || []).map((e) => `<blockquote class="source"><span class="note">${esc(e.title || e.source)}</span><br>${highlight(e.span, [String(x.value)])}</blockquote>`).join("")).join("")}
      ${(f.warnings || []).map((w) => `<p class="status">${esc(w)}</p>`).join("")}</section>`;
  }
  if (n.status === "scored") {
    const N = n.behaviorgpt?.of || Object.keys(S.boot.catalog).length;
    html += `<section><h3>Is this step normal?</h3><dl class="kv">
      <dt>Step model</dt><dd>${esc(RANKER_LABEL[ck.ranker] || ck.ranker || "")}: rank ${n.rank} of ${N}</dd>
      <dt>Risk</dt><dd>${Math.round((n.risk || 0) * 100)}% of the pause line</dd>
      <dt>Expected</dt><dd>${(n.expected || []).map((x) => esc(x.name)).join("<br>") || "n/a"}</dd>
      ${n.missing?.length ? `<dt>Usually before this</dt><dd>${n.missing.map(esc).join("<br>")}</dd>` : ""}
      <dt>BehaviorGPT</dt><dd>${n.behaviorgpt?.rank ? `rank ${n.behaviorgpt.rank} of ${n.behaviorgpt.of}; top guesses: ${(n.behaviorgpt.top || []).map((x) => esc(x.name)).join("; ")}` : "not available for this step"}<br><span class="note">Shown as evidence. It doesn't change the decision.</span></dd></dl></section>`;
  }
  if (r.violations?.length || r.precedents?.length) {
    html += `<section><h3>Rules</h3><ul class="rules">${r.violations.map((v) => `<li><span class="who">${esc(v.author ? `${v.author}, unwritten` : v.source || "Written policy")}</span>${esc(v.text)}</li>`).join("")}${(r.precedents || []).map((v) => `<li><span class="who">Your rule</span>${esc(v.text || v.reason || "")}</li>`).join("")}</ul></section>`;
  }
  openDrawer(`Step ${st.index + 1}: ${stepTitle(st)}`, html || '<p class="note">Nothing to flag: this step passed every check.</p>');
  $("#open-page")?.addEventListener("click", () => {
    navigateApp(st.page);
    closeDrawer();
    if (matchMedia("(max-width: 900px)").matches) showAppPane(true);
  });
}

async function openSetup() {
  const b = S.boot;
  if (!b) return;
  openDrawer("Company and rules", '<p class="note">Loading the rules…</p>');
  let r;
  try {
    r = await api("/api/rules");
  } catch (e) {
    $("#drawer-body").innerHTML = `<p class="status err">Couldn't load the rules: ${esc(e.message)}</p>`;
    return;
  }
  const list = (items, who, text) => items.length
    ? items.map((x) => `<li><span class="who">${esc(who(x))}</span>${esc(text(x))}</li>`).join("")
    : '<li class="note">None yet.</li>';
  const actionName = (id) => b.catalog?.[id]?.name || id || "any step";
  $("#drawer-body").innerHTML = `
    <section>
      <h3>${esc(b.company.name)}</h3>
      <p>The agent works as ${esc(b.company.persona)}, on ${esc(b.scenario.account)}. It reads the written rules in the company's documents. The unwritten rules stay with the monitor only.</p>
    </section>
    <section><h3>Written rules</h3><ul class="rules">${list(r.written || [], (x) => x.source || "Company policy", (x) => x.text)}</ul></section>
    <section><h3>Unwritten rules</h3><ul class="rules">${list(r.unwritten || [], (x) => `${x.author}, team know-how`, (x) => x.text)}</ul></section>
    <section><h3>Rules you taught it</h3><p class="note">Every reason you give when you allow a paused step becomes one of these.</p>
      <ul class="rules">${list(r.learned || [], (x) => `${x.decision === "allow" ? "Allowed" : "Blocked"}: ${actionName(x.catalog_action)}`, (x) => `“${x.reason}”`)}</ul></section>
    ${catalogSection()}`;
  wireCatalog();
}

/* Catalog upload (BehaviorGPT): kept from the earlier canvas; needs the server. */
function catalogSection() {
  if (FIXTURE) return '<section><h3>Action catalog</h3><p class="note">Uploading a catalog needs the server; it isn\'t available in fixture mode.</p></section>';
  return `<section>
      <h3>Your catalogs on the Unbox portal</h3>
      <p class="note">Catalogs uploaded with your API key are the ones on the <a href="https://portal.unboxai.com/catalogs/" target="_blank" rel="noopener">portal's Catalogs page</a>. Each key holds 2.</p>
      <ul class="rules" id="portal-cats"><li class="note">Loading…</li></ul>
    </section>
    <section>
      <h3>Upload an action catalog</h3>
      <p class="note">A CSV of the actions your agents can take, one per row: id, name, event_type and group (product). BehaviorGPT reads each action's name. Uploading under an existing name refreshes that catalog.</p>
      <input type="file" id="cat-file" accept=".csv,text/csv" aria-label="Catalog CSV">
      <label for="cat-name">Catalog name on the portal</label><input type="text" id="cat-name" value="company_actions" pattern="[a-z0-9][a-z0-9_\\-]{1,62}">
      <div class="row-actions"><button class="ghost" id="cat-check">Check file</button><button class="primary" id="cat-embed" disabled>Embed with BehaviorGPT</button><span class="status" id="cat-status" role="status"></span></div>
      <div id="cat-out"></div>
    </section>`;
}

function wireCatalog() {
  if (FIXTURE) return;
  const upload = async (embed) => {
    const f = $("#cat-file").files[0], st = $("#cat-status");
    if (!f) { st.textContent = "Choose a CSV first."; st.className = "status err"; return; }
    const fd = new FormData();
    fd.append("file", f);
    st.className = "status";
    st.textContent = embed ? "Uploading to BehaviorGPT…" : "Checking…";
    try {
      const name = encodeURIComponent($("#cat-name").value.trim());
      const r = await fetch(`/api/catalog/upload?embed=${embed}&name=${name}`, { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.statusText);
      $("#cat-out").innerHTML = `<p>${j.rows} actions${j.errors.length ? `. Fix first: ${esc(j.errors.join("; "))}` : ", ready to embed"}.</p><ul class="rules">${j.sample.map((x) => `<li><span class="who">${esc(x.id)}</span>${esc(x.name)}</li>`).join("")}</ul>`;
      $("#cat-embed").disabled = !!j.errors.length;
      st.textContent = "";
      if (j.job_id) pollEmbed(j.job_id);
    } catch (e) { st.textContent = e.message; st.className = "status err"; }
  };
  $("#cat-check").onclick = () => upload(false);
  $("#cat-embed").onclick = () => upload(true);
  loadPortalCatalogs();
}

async function loadPortalCatalogs() {
  const ul = $("#portal-cats");
  if (!ul) return;
  try {
    const c = await api("/api/catalogs");
    if (!c.available) {
      ul.innerHTML = `<li class="note">Add UNBOXAI_API_KEY on the server to see them here.${c.record ? ` This app uses <strong>${esc(c.record.catalog_name)}</strong> (${esc(c.record.catalog_id)}).` : ""}</li>`;
      return;
    }
    ul.innerHTML = c.owned.map((x) => `<li><span class="who">${esc(x.status)}${x.catalog_id === c.current ? ", used by this app" : ""}</span><strong>${esc(x.name)}</strong> <span class="note">${esc(x.catalog_id)}</span></li>`).join("") +
      `<li class="note">${c.owned.length} of ${c.slots} slots used.</li>`;
  } catch (e) {
    ul.innerHTML = `<li class="note">Catalog listing isn't available on this server (${esc(e.message)}).</li>`;
  }
}

async function pollEmbed(jobId) {
  const st = $("#cat-status");
  for (let i = 0; i < 120; i++) {
    const j = await api(`/api/catalog/status?job_id=${encodeURIComponent(jobId)}`).catch((e) => ({ error: e.message }));
    if (!st.isConnected) return;
    if (j.error) { st.textContent = j.error; st.className = "status err"; return; }
    st.textContent = `Embedding: ${j.status || "queued"}…`;
    if (j.catalog_id && /ready|done|succeeded|complete/i.test(j.status || "")) {
      st.textContent = `Embedded as ${j.catalog_id}. It's on your Unbox portal now.`;
      loadPortalCatalogs();
      return;
    }
    await sleep(5000);
  }
}

init();
