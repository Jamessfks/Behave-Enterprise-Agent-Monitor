"use strict";
/* Agent Monitor front end. Holds each run in the browser; the server only checks steps. */

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const REDUCE = matchMedia("(prefers-reduced-motion: reduce)").matches;
const STEP_MS = REDUCE ? 200 : 600;

async function api(path, body, opts = {}) {
  const init = body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, { ...init, ...opts });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : `${r.status} ${r.statusText}`);
  return j;
}

const ICON = {
  Trigger: '<path d="M4 6h16v12H4z M4 7l8 6 8-6"/>',
  Mail: '<path d="M4 6h16v12H4z M4 7l8 6 8-6"/>',
  Files: '<path d="M7 3h7l4 4v14H7z M14 3v4h4 M10 12h5 M10 16h5"/>',
  Calls: '<path d="M6 4h3l2 5-2 1a11 11 0 0 0 5 5l1-2 5 2v3a2 2 0 0 1-2 2A16 16 0 0 1 4 6a2 2 0 0 1 2-2z"/>',
  CRM: '<path d="M4 20V8l8-4 8 4v12 M9 20v-6h6v6 M4 20h16"/>',
  Quotes: '<path d="M6 3h12v18l-3-2-3 2-3-2-3 2z M9 8h6 M9 12h6"/>',
  Chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  Calendar: '<path d="M4 6h16v14H4z M4 10h16 M8 3v4 M16 3v4"/>',
};
const glyph = (app) =>
  `<span class="glyph" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round">${ICON[app] || ICON.CRM}</svg></span>`;

const EDGE = `<svg viewBox="0 0 40 56" aria-hidden="true">
  <line class="base" x1="20" y1="0" x2="20" y2="46"/>
  <line class="current" x1="20" y1="0" x2="20" y2="46"/>
  <path class="arc" d="M20 4 l-9 8 l13 7 l-11 9 l10 8 l-5 7"/>
  <circle class="spark" cx="20" cy="3" r="2.6"/>
  <path class="head" d="M14 45 L20 55 L26 45 Z"/></svg>`;

const RANKER_LABEL = { workflow: "Company workflow", behaviorgpt: "BehaviorGPT only", blend: "Blend" };

const S = {
  boot: null,
  ctx: null,
  ranker: null,
  run: "careful_01",
  busy: false,
  risks: [],
  flags: [],
  latency: [],
  done: {},
};

/* ---------- boot ---------- */
async function init() {
  try {
    S.boot = await api("/api/bootstrap");
  } catch (e) {
    $("#chain").innerHTML = `<li class="note">Couldn't reach the server: ${esc(e.message)}. Start it with <code>uv run uvicorn server:app</code>.</li>`;
    return;
  }
  S.ctx = structuredClone(S.boot.context);
  S.ranker = S.boot.default_ranker;
  const sel = $("#ranker");
  for (const k of Object.keys(S.boot.rankers)) {
    const o = new Option(RANKER_LABEL[k] || k, k);
    o.selected = k === S.ranker;
    sel.add(o);
  }
  sel.addEventListener("change", () => { S.ranker = sel.value; rankerNote(); });
  rankerNote();
  $("#instruction").value = S.boot.trigger.text;
  const segs = [...document.querySelectorAll(".seg button")];
  segs.forEach((b, i) => {
    b.addEventListener("click", () => pickRun(b.dataset.run));
    b.addEventListener("keydown", (e) => {
      const d = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (!d || S.busy) return;
      e.preventDefault();
      const next = segs[(i + d + segs.length) % segs.length];
      pickRun(next.dataset.run);
      next.focus();
    });
  });
  $("#ledger-toggle").addEventListener("click", (e) => {
    const open = $("#ledger").classList.toggle("open");
    e.currentTarget.setAttribute("aria-expanded", String(open));
    e.currentTarget.textContent = open ? "Hide steps" : "Show every step";
  });
  $("#play").addEventListener("click", () => (S.run === "live" ? playLive() : playReplay()));
  $("#setup").addEventListener("click", openSetup);
  $("#drawer").addEventListener("click", (e) => { if (e.target.id === "drawer" || e.target.closest("[data-close]")) closeDrawer(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#drawer").hidden) closeDrawer(); });
  reset();
}

function rankerNote() {
  const r = S.boot.rankers[S.ranker];
  const g = S.boot.go_no_go;
  let t;
  if (S.ranker === "workflow") {
    t = `Decides when to pause. Learned from this company's approved runs: in calibration it caught ${r.caught.length} of ${r.caught.length + r.missed.length} behavior mistakes with ${r.false_alarms.length} false alarms. BehaviorGPT also ranks every step; its rank is shown as evidence and doesn't change any decision.`;
  } else if (S.ranker === "behaviorgpt") {
    t = `For comparison: BehaviorGPT decides on its own. It ranked the correct next step at a median of #${g.careful_median_rank} of ${g.catalog_size} and caught ${r.caught.length} of ${r.caught.length + r.missed.length} behavior mistakes in calibration.`;
  } else {
    t = `For comparison: BehaviorGPT's ranking combined with the company's workflow. Caught ${r.caught.length}, missed ${r.missed.length}, ${r.false_alarms.length} false alarms in calibration.`;
  }
  $("#ranker-note").textContent = t;
}

function pickRun(run) {
  if (S.busy) return;
  S.run = run;
  document.querySelectorAll(".seg button").forEach((b) => {
    b.setAttribute("aria-checked", String(b.dataset.run === run));
    b.tabIndex = b.dataset.run === run ? 0 : -1;
  });
  $("#live-box").hidden = run !== "live";
  $("#live-note").textContent = run === "live" && !S.boot.live_available
    ? "Live mode needs an Anthropic API key on the server (ANTHROPIC_API_KEY). The two recorded agents work without one."
    : run === "live" ? "A Claude agent will work in the fake business app. Every step it takes is checked before it runs." : "";
  reset();
}

/* ---------- chain ---------- */
function reset(idle = true) {
  S.risks = []; S.flags = []; S.latency = [];
  $("#chain").innerHTML = "";
  $("#ledger").innerHTML = "";
  $("#summary").hidden = true;
  drawRisk();
  $("#risk-now").textContent = "Risk 0%";
  $("#latency").textContent = "";
  const t = S.boot.trigger;
  const text = S.run === "live" ? $("#instruction").value : t.text;
  const li = document.createElement("li");
  li.className = "node trigger";
  li.innerHTML = `${glyph("Trigger")}<div class="title">Request from ${esc(t.from.split(" (")[0])}</div><div class="checks"></div><div class="meta">${esc(text.length > 150 ? text.slice(0, 150) + "…" : text)}</div>`;
  $("#chain").append(li);
  if (idle) {
    for (const name of ["Read the sources", "Update the CRM and the quote", "Coordinate and follow up"]) {
      const e = document.createElement("li");
      e.className = "edge ghost";
      e.setAttribute("aria-hidden", "true");
      e.innerHTML = EDGE;
      const g = document.createElement("li");
      g.className = "node ghost-step";
      g.setAttribute("aria-hidden", "true");
      g.innerHTML = `${glyph("CRM")}<div class="title">${name}</div><div class="checks"></div>`;
      $("#chain").append(e, g);
    }
    $("#chain").insertAdjacentHTML("beforeend", '<li class="idle-hint">Press Play to watch each step get checked before it runs.</li>');
  }
  $("#play").disabled = S.run === "live" && !S.boot.live_available;
  $("#play").textContent = "Play";
}

function title(ev) {
  if (ev.type === "search") return `Search ${ev.details.app} for “${ev.query}”`;
  const a = S.boot.catalog[ev.action_id];
  return a ? a.name : ev.action_id;
}

function addStep(ev) {
  const edge = document.createElement("li");
  edge.className = "edge running";
  edge.setAttribute("aria-hidden", "true");
  edge.innerHTML = EDGE;
  const node = document.createElement("li");
  node.className = "node running";
  node.innerHTML = `${glyph(ev.details.app)}<div class="title">${esc(title(ev))}</div><div class="checks"><span class="chip">checking…</span></div><div class="meta">${esc(metaLine(ev))}</div><button class="open" aria-label="Details: ${esc(title(ev))}"></button>`;
  $("#chain").append(edge, node);
  if (!REDUCE) node.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return { edge, node };
}

function metaLine(ev) {
  const v = ev.details.values;
  if (v) return Object.entries(v).filter(([k]) => k !== "message").map(([k, x]) => `${k.replaceAll("_", " ")}: ${x}`).join(", ") || ev.details.app;
  if (ev.details.source) return S.boot.sources[ev.details.source]?.title || ev.details.app;
  return ev.details.app + (ev.details.entity ? `, ${ev.details.entity}` : "");
}

function chips(res) {
  const c = res.checks, out = [];
  if (c.normal.status === "scored") out.push(c.normal.ok ? '<span class="chip ok">normal</span>' : '<span class="chip bad">unusual</span>');
  if (c.facts.checked.length) {
    out.push(!c.facts.ok ? '<span class="chip bad">unsupported</span>'
      : c.facts.warnings.length ? '<span class="chip warn">sources disagree</span>' : '<span class="chip ok">facts</span>');
  }
  if (c.rules.violations.length || c.rules.precedents.length || res.irreversible) out.push(c.rules.ok ? '<span class="chip ok">rules</span>' : '<span class="chip bad">breaks rule</span>');
  return out.join("") || '<span class="chip ok">passed</span>';
}

function settle(node, edge, ev, res) {
  node.classList.remove("running");
  node.querySelector(".checks").innerHTML = chips(res);
  if (res.verdict === "allowed_by_rule") {
    node.classList.add("allowed");
    node.querySelector(".meta").textContent = `Allowed by your earlier rule: “${res.precedent}”`;
  } else if (res.checks.facts.warnings.length) {
    node.querySelector(".meta").textContent = `${metaLine(ev)}. ${res.checks.facts.warnings[0]}`;
  }
  edge.className = "edge " + (res.verdict === "pause" ? "paused" : "passed");
  if (res.verdict === "pause") node.classList.add("paused");
  node.querySelector(".open").onclick = () => openStep(ev, res);
}

/* ---------- monitor ---------- */
function ledgerRow(ev, res) {
  const n = res.checks.normal, N = Object.keys(S.boot.catalog).length;
  const flag = res.verdict === "pause";
  const li = document.createElement("li");
  li.className = "row" + (flag ? " flag" : "");
  let bar = "", rank = "", more = "";
  if (n.status === "scored") {
    const exp = Math.max(0.04, (N - n.rank + 1) / N);
    bar = `<div class="bar-exp" role="img" aria-label="How expected: rank ${n.rank} of ${N}"><i style="width:${(exp * 100).toFixed(0)}%"></i></div>`;
    rank = `#${n.rank}/${N}`;
    const guess = n.expected.slice(0, 2).map((x) => esc(x.name)).join("; ");
    const role = res.ranker === "workflow" ? "BehaviorGPT, as evidence" : "BehaviorGPT";
    const bg = n.behaviorgpt.rank ? `${role}: ranked it #${n.behaviorgpt.rank} of ${n.behaviorgpt.of}; its top guess: ${esc(n.behaviorgpt.top[0]?.name ?? "n/a")}.` : `${role}: not available for this step.`;
    more = `<details${flag ? " open" : ""}><summary>${flag ? "Why it stopped" : "What was expected"}</summary><p>Expected next: ${guess}.</p><p>${bg}</p></details>`;
  } else {
    bar = '<span></span>';
    rank = n.status === "context" ? "search" : "repeat";
  }
  li.innerHTML = `<span class="n">${ev.step + 1}</span><span class="what" title="${esc(title(ev))}">${esc(flag ? "Paused: " + title(ev) : title(ev))}</span>${bar}<span class="rank">${rank}</span>${more}`;
  $("#ledger").prepend(li);
}

function drawRisk() {
  const svg = $("#risk-chart"), W = 300, H = 64, top = 1.4;
  const pts = S.risks;
  const y = (r) => H - Math.min(r, top) / top * (H - 6) - 3;
  const x = (i) => (pts.length < 2 ? 0 : (i / (pts.length - 1)) * W);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.risk).toFixed(1)}`).join(" ");
  svg.innerHTML = `<line class="baseline" x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}"/><line class="barrier" x1="0" x2="${W}" y1="${y(1)}" y2="${y(1)}"/>${line ? `<path class="line" d="${line}"/>` : ""}` +
    pts.map((p, i) => (p.flag ? `<circle class="flag" cx="${x(i)}" cy="${y(Math.max(p.risk, 1))}" r="3.5"/>` : "")).join("");
}

function track(ev, res) {
  const n = res.checks.normal;
  S.risks.push({ risk: n.risk || 0, flag: res.verdict === "pause" });
  drawRisk();
  $("#risk-now").textContent = `Risk ${Math.round((n.risk || 0) * 100)}%`;
  S.latency.push(res.latency_ms);
  const avg = (k) => (S.latency.reduce((a, l) => a + l[k], 0) / S.latency.length).toFixed(1);
  $("#latency").textContent = `Check time per step, server side: step model ${avg("normal")} ms, facts ${avg("facts")} ms, rules ${avg("rules")} ms.`;
}

/* ---------- pause ---------- */
function pauseCard(node, ev, res) {
  return new Promise((resolve) => {
    const card = document.createElement("li");
    card.className = "pause";
    card.setAttribute("aria-label", "Paused step: decide");
    card.tabIndex = -1;
    const marco = res.reasons.filter((r) => r.startsWith("Marco would stop here"));
    const other = res.reasons.filter((r) => !r.startsWith("Marco would stop here"));
    const by = res.failed.map((f) => ({ normal: "step model", facts: "fact check", rules: "rules check" })[f]).join(", ");
    card.innerHTML = `<h3>Paused before this step ran</h3>
      <ul>${other.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
      ${marco.map((m) => `<blockquote class="marco">${esc(m)}</blockquote>`).join("")}
      <p class="hint">Caught by: ${esc(by)}.</p>
      <label for="why-${ev.step}" id="why-hint-${ev.step}">To allow it, say why. Your reason becomes a rule for next time.</label>
      <textarea id="why-${ev.step}" rows="2" placeholder="For example: the client confirmed this by phone"></textarea>
      <div class="actions"><button class="primary" data-allow disabled aria-describedby="why-hint-${ev.step}">Allow</button><button class="danger" data-block>Block</button></div>`;
    node.after(card);
    const why = card.querySelector("textarea"), allow = card.querySelector("[data-allow]");
    why.addEventListener("input", () => { allow.disabled = !why.value.trim(); });
    const done = async (decision) => {
      card.querySelectorAll("button, textarea").forEach((x) => (x.disabled = true));
      let rule = null;
      if (decision === "allow") {
        rule = await api("/api/rules/learn", { event: ev, failed: res.failed, reason: why.value });
        S.ctx.learned_rules.push(rule);
      }
      card.remove();
      resolve({ decision, reason: why.value.trim(), rule });
    };
    allow.addEventListener("click", () => done("allow"));
    card.querySelector("[data-block]").addEventListener("click", () => done("block"));
    card.scrollIntoView({ block: "center", behavior: REDUCE ? "auto" : "smooth" });
    card.focus({ preventScroll: true });
  });
}

function decided(node, edge, ev, res, d) {
  node.classList.remove("paused");
  node.classList.add(d.decision === "allow" ? "allowed" : "blocked");
  edge.className = "edge " + (d.decision === "allow" ? "passed" : "blocked");
  node.querySelector(".meta").textContent = d.decision === "allow" ? `Allowed: “${d.reason}”. Saved as a rule.` : "Blocked. The step never ran.";
  S.flags.push({ step: ev.step + 1, name: title(ev), failed: res.failed, decision: d.decision, reason: d.reason });
}

/* ---------- replay ---------- */
async function playReplay() {
  if (S.busy) return;
  reset(false);
  S.busy = true;
  $("#play").disabled = true;
  $("#play").textContent = "Running…";
  const run = S.boot.runs[S.run];
  const history = [];
  let cusum = 0;
  try {
    for (const ev of run) {
      const { edge, node } = addStep(ev);
      const [res] = await Promise.all([
        api("/api/check", { history, event: ev, context: S.ctx, cusum, ranker: S.ranker }),
        sleep(STEP_MS),
      ]);
      settle(node, edge, ev, res);
      ledgerRow(ev, res);
      track(ev, res);
      if (res.verdict === "pause") {
        const d = await pauseCard(node, ev, res);
        decided(node, edge, ev, res, d);
        if (d.decision === "allow") history.push(ev);
        cusum = 0;
      } else {
        history.push(ev);
        cusum = res.checks.normal.cusum;
      }
    }
    S.done[S.run] = { steps: run.length, flags: S.flags.slice() };
    summary();
  } catch (e) {
    $("#chain").insertAdjacentHTML("beforeend", `<li class="note status err">Stopped: ${esc(e.message)}</li>`);
  } finally {
    S.busy = false;
    $("#play").disabled = false;
    $("#play").textContent = "Play again";
  }
}

function summary() {
  const box = $("#summary");
  const flags = S.flags;
  const rows = flags.map((f) => `<tr><td>${f.step}</td><td>${esc(f.name)}</td><td>${esc(f.failed.join(", "))}</td><td>${f.decision === "allow" ? "Allowed" : "Blocked"}</td></tr>`).join("");
  let html = `<h3>${flags.length ? `${flags.length} step${flags.length > 1 ? "s" : ""} paused for a person` : "No step needed a person"}</h3>`;
  if (flags.length) html += `<table class="compare"><thead><tr><th>Step</th><th>Action</th><th>Caught by</th><th>Decision</th></tr></thead><tbody>${rows}</tbody></table>`;
  const c = S.done.careful_01, f = S.done.faulty;
  if (c && f) {
    const caught = (x) => x.flags.map((y) => `${y.name} (${y.failed.join(", ")})`).join("; ") || "nothing";
    html += `<h3 style="margin-top:16px">Both agents, same task</h3><table class="compare"><thead><tr><th></th><th>Careful</th><th>Faulty</th></tr></thead><tbody>
      <tr><th>Steps</th><td>${c.steps}</td><td>${f.steps}</td></tr>
      <tr><th>Paused</th><td>${c.flags.length}</td><td>${f.flags.length}</td></tr>
      <tr><th>What was caught</th><td>${esc(caught(c))}</td><td>${esc(caught(f))}</td></tr></tbody></table>`;
  } else {
    html += `<p class="note">Play the ${S.run === "faulty" ? "careful" : "faulty"} agent too, to compare both runs side by side.</p>`;
  }
  box.innerHTML = html;
  box.hidden = false;
}

/* ---------- live ---------- */
async function playLive() {
  if (S.busy || !S.boot.live_available) return;
  reset(false);
  S.busy = true;
  $("#play").disabled = true;
  $("#play").textContent = "Agent working…";
  let p;
  try {
    p = await api("/api/agent/start", { instruction: $("#instruction").value, context: S.ctx, ranker: S.ranker });
    for (let turn = 0; turn < 60; turn++) {
      p = await api("/api/agent/step", p);
      for (const s of p.steps) {
        const { edge, node } = addStep(s.event);
        await sleep(STEP_MS / 2);
        settle(node, edge, s.event, s.check);
        ledgerRow(s.event, s.check);
        track(s.event, s.check);
        if (s.check.verdict === "pause") {
          const d = await pauseCard(node, s.event, s.check);
          decided(node, edge, s.event, s.check, d);
          p.resolution = { decision: d.decision, reason: d.reason };
          p.context = S.ctx;
        }
      }
      if (p.done) break;
    }
    S.done.live = { steps: p.history.length, flags: S.flags.slice() };
    summary();
    if (p.state?.summary) $("#summary").insertAdjacentHTML("afterbegin", `<p>${esc(p.state.summary)}</p>`);
  } catch (e) {
    $("#chain").insertAdjacentHTML("beforeend", `<li class="note status err">Stopped: ${esc(e.message)}</li>`);
  } finally {
    S.busy = false;
    $("#play").disabled = false;
    $("#play").textContent = "Run again";
  }
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

function highlight(text, spans) {
  let out = esc(text);
  for (const s of spans) out = out.split(esc(s)).join(`<mark>${esc(s)}</mark>`);
  return out;
}

function openStep(ev, res) {
  const n = res.checks.normal, f = res.checks.facts, r = res.checks.rules;
  let html = "";
  if (res.reasons.length) html += `<section><h3>Why it paused</h3><ul>${res.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></section>`;
  if (ev.details.values) html += `<section><h3>What the agent entered</h3><dl class="kv">${Object.entries(ev.details.values).map(([k, v]) => `<dt>${esc(k.replaceAll("_", " "))}</dt><dd>${esc(v)}</dd>`).join("")}</dl></section>`;
  if (f.checked.length) {
    html += `<section><h3>Fact check</h3>${f.checked.map((c) => `<p><strong>${esc(c.field.replaceAll("_", " "))} = ${esc(c.value)}</strong>: ${c.ok ? "found" : "not supported"}${c.expected ? ` (expected ${esc(c.expected.join(" or "))})` : ""}</p>` +
      (c.evidence || []).map((e) => `<blockquote class="source"><span class="note">${esc(e.title)}</span><br>${highlight(e.span, [String(c.value)])}</blockquote>`).join("")).join("")}
      ${f.warnings.map((w) => `<p class="status">${esc(w)}</p>`).join("")}</section>`;
  }
  if (ev.details.source && S.boot.sources[ev.details.source]) {
    const s = S.boot.sources[ev.details.source];
    html += `<section><h3>${esc(s.title)}</h3><p class="source">${esc(s.text)}</p></section>`;
  }
  if (n.status === "scored") {
    html += `<section><h3>Is this step normal?</h3><dl class="kv">
      <dt>Step model</dt><dd>${esc(RANKER_LABEL[res.ranker] || res.ranker)}: rank ${n.rank} of ${Object.keys(S.boot.catalog).length}</dd>
      <dt>Risk</dt><dd>${Math.round(n.risk * 100)}% of the pause barrier</dd>
      <dt>Expected</dt><dd>${n.expected.map((x) => esc(x.name)).join("<br>")}</dd>
      ${n.missing.length ? `<dt>Usually after</dt><dd>${n.missing.map(esc).join("<br>")}</dd>` : ""}
      <dt>BehaviorGPT</dt><dd>${n.behaviorgpt.rank ? `rank ${n.behaviorgpt.rank} of ${n.behaviorgpt.of}; top guesses: ${n.behaviorgpt.top.map((x) => esc(x.name)).join("; ")}` : "not available for this step"}${res.ranker === "workflow" ? "<br><span class=\"note\">Shown as evidence. It doesn't change the decision.</span>" : ""}</dd></dl></section>`;
  }
  if (r.violations.length || r.precedents.length) {
    html += `<section><h3>Rules</h3><ul class="rules">${r.violations.map((v) => `<li><span class="who">${esc(v.author ? `${v.author}, unwritten` : v.source || "Policy")}</span>${esc(v.text)}</li>`).join("")}${r.precedents.map((v) => `<li><span class="who">Your rule</span>${esc(v.text)}</li>`).join("")}</ul></section>`;
  }
  openDrawer(`Step ${ev.step + 1}: ${title(ev)}`, html || '<p class="note">Nothing to flag: this step passed every check.</p>');
}

function ruleList(rules, group) {
  return rules.map((r, i) => `<li><span class="who">${esc(r.author ? r.author : r.source || "Policy")}${r.kind === "advisory" ? ", shown to people only" : ""}</span>${esc(r.text)}${group === "learned_rules" ? ` <button class="ghost" data-del="${i}">Remove</button>` : ""}</li>`).join("") || '<li class="note">None yet.</li>';
}

function openSetup() {
  const c = S.ctx;
  openDrawer("Company and catalog", `
    <section>
      <h3>Company background</h3>
      <p class="note">The agent reads this, plus the written policies. Unwritten rules stay with the monitor only.</p>
      <label for="c-name">Company</label><input type="text" id="c-name" value="${esc(c.company)}">
      <label for="c-bg">Background</label><textarea id="c-bg" rows="5">${esc(c.background)}</textarea>
      <div class="row-actions"><button class="primary" id="c-save">Save context</button><span class="status" id="c-status" role="status"></span></div>
    </section>
    <section><h3>Written policies</h3><ul class="rules">${ruleList(c.written_policies)}</ul></section>
    <section><h3>Unwritten rules</h3><ul class="rules" id="unwritten">${ruleList(c.unwritten_rules)}</ul>
      <label for="u-text">Add how a senior person works</label><textarea id="u-text" rows="2" placeholder="For example: never offer a trial before security review"></textarea>
      <label for="u-who">Whose rule</label><input type="text" id="u-who" value="Marco">
      <div class="row-actions"><button class="ghost" id="u-add">Add rule</button></div></section>
    <section><h3>Rules you taught it</h3><ul class="rules" id="learned">${ruleList(c.learned_rules, "learned_rules")}</ul></section>
    <section>
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
    </section>`);
  $("#c-save").onclick = async () => {
    try {
      const r = await api("/api/context/validate", { context: { ...S.ctx, company: $("#c-name").value, background: $("#c-bg").value } });
      if (r.errors.length) { $("#c-status").textContent = r.errors.join("; "); $("#c-status").className = "status err"; return; }
      S.ctx = r.context;
      $("#c-status").textContent = "Saved. The next run uses it.";
      $("#c-status").className = "status";
    } catch (e) { $("#c-status").textContent = e.message; $("#c-status").className = "status err"; }
  };
  $("#u-add").onclick = () => {
    const text = $("#u-text").value.trim();
    if (!text) return;
    S.ctx.unwritten_rules.push({ id: `unwritten.${Date.now()}`, kind: "advisory", author: $("#u-who").value.trim() || "Team", text });
    $("#unwritten").innerHTML = ruleList(S.ctx.unwritten_rules);
    $("#u-text").value = "";
  };
  $("#learned").onclick = (e) => {
    const i = e.target.dataset?.del;
    if (i === undefined) return;
    S.ctx.learned_rules.splice(Number(i), 1);
    $("#learned").innerHTML = ruleList(S.ctx.learned_rules, "learned_rules");
  };
  const upload = async (embed) => {
    const f = $("#cat-file").files[0];
    const st = $("#cat-status");
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
      if (j.job_id) pollEmbed(j.job_id, j.sample);
    } catch (e) { st.textContent = e.message; st.className = "status err"; }
  };
  loadPortalCatalogs();
  $("#cat-check").onclick = () => upload(false);
  $("#cat-embed").onclick = () => upload(true);
}

async function loadPortalCatalogs() {
  const ul = $("#portal-cats");
  try {
    const c = await api("/api/catalogs");
    if (!c.available) {
      ul.innerHTML = `<li class="note">Add UNBOXAI_API_KEY on the server to see them here.${c.record ? ` This app uses <strong>${esc(c.record.catalog_name)}</strong> (${esc(c.record.catalog_id)}).` : ""}</li>`;
      return;
    }
    ul.innerHTML = c.owned.map((x) => `<li><span class="who">${esc(x.status)}${x.catalog_id === c.current ? ", used by this app" : ""}</span><strong>${esc(x.name)}</strong> <span class="note">${esc(x.catalog_id)}</span></li>`).join("") +
      `<li class="note">${c.owned.length} of ${c.slots} slots used.</li>`;
  } catch (e) {
    ul.innerHTML = `<li class="status err">${esc(e.message)}</li>`;
  }
}

async function pollEmbed(jobId, sample) {
  const st = $("#cat-status");
  for (let i = 0; i < 120; i++) {
    const j = await api(`/api/catalog/status?job_id=${encodeURIComponent(jobId)}`).catch((e) => ({ error: e.message }));
    if (j.error) { st.textContent = j.error; st.className = "status err"; return; }
    st.textContent = `Embedding: ${j.status || "queued"}…`;
    if (j.catalog_id && /ready|done|succeeded|complete/i.test(j.status || "")) {
      st.textContent = `Embedded as ${j.catalog_id}. It's on your Unbox portal now.`;
      loadPortalCatalogs();
      const first = sample[0]?.id;
      if (first) {
        const p = await api("/api/catalog/preview", { catalog_id: j.catalog_id, after: [first] }).catch(() => null);
        if (p) $("#cat-out").insertAdjacentHTML("beforeend", `<p>After “${esc(sample[0].name)}”, BehaviorGPT expects:</p><ol>${p.next.map((x) => `<li>${esc(x.name)}</li>`).join("")}</ol>`);
      }
      return;
    }
    await sleep(5000);
  }
}

init();
