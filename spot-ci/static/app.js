/* Spot India CI console. Vanilla JS + Chart.js. All numbers come from /api/dashboard. */
(() => {
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const compact = (n) => { if (n == null) return "n/a"; const a = Math.abs(n); const f = (x, u) => (Math.round(x * 10) / 10).toString().replace(/\.0$/, "") + u; return a >= 1e9 ? f(n / 1e9, "B") : a >= 1e6 ? f(n / 1e6, "M") : a >= 1e3 ? f(n / 1e3, "K") : String(Math.round(n)); };
const inr = (n) => (n >= 1e7 ? `₹${(n / 1e7).toFixed(2)} Cr` : n >= 1e5 ? `₹${(n / 1e5).toFixed(1)} L` : `₹${Math.round(n).toLocaleString("en-IN")}`);
const fmtDate = (s, prec) => { if (!s) return "n/a"; const d = new Date(s + "T00:00:00"); return prec === "year" ? String(d.getFullYear()) : prec === "month" ? d.toLocaleDateString("en-GB", { month: "short", year: "numeric" }) : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); };
const SHAPES = [["circle", "circle"], ["triangle", "tri"], ["rect", "rect"], ["rectRot", "diamond"], ["star", "star"], ["cross", "cross"]];
const SPOT_PH = { 1: ["Validate", "Months 0-3"], 2: ["Launch", "Months 3-9"], 3: ["Traction", "Months 9-24"], 4: ["Scale", "Months 24-48"], 5: ["Entrench", "Month 48+"] };
const TYPE_LABEL = { differentiator: "Your unique edge", "table-stakes": "Table stakes", fix: "Fix their failure", gtm: "Go to market", monetise: "Monetise" };

let LIVE = null, CFG = null, D = null, charts = {}, months = [], timer = null, revBuilt = false;
const cfg = { from: "2012-01-01", asof: null, competitors: null, phases: null, types: null, built: [], usp: null, assumptions: {} };

const isDark = () => document.documentElement.dataset.theme === "dark" || (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
const colorOf = (c) => (isDark() ? c.color_dark : c.color);
const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const idx = (id) => CFG.competitors.findIndex((c) => c.id === id);
const swatch = (id, color) => `<span class="sw ${SHAPES[idx(id) % 6][1]}" style="background:${color}"></span>`;

async function api(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}

/* ---------------------------------------------------------------- init */
async function init() {
  CFG = await (await fetch("/api/config")).json();
  cfg.competitors = CFG.competitors.map((c) => c.id);
  cfg.phases = CFG.phases.map((p) => p.id);
  cfg.types = [...CFG.event_types];
  cfg.usp = [...CFG.usp];
  if (CFG.stateless) { try { LIVE = JSON.parse(localStorage.getItem("spot_ci_live") || "null"); } catch (e) { LIVE = null; } cfg.live = LIVE; }
  cfg.assumptions = { ...CFG.defaults, ulb_adds: { ...CFG.defaults.ulb_adds } };
  // month index for the as-of slider, ending today
  const end = new Date(); const y0 = 2012;
  for (let y = y0; y <= end.getFullYear(); y++) for (let m = 0; m < 12; m++) { if (y === end.getFullYear() && m > end.getMonth()) break; months.push(new Date(Date.UTC(y, m + 1, 0))); }
  months[months.length - 1] = new Date(Date.UTC(end.getFullYear(), end.getMonth(), end.getDate()));
  const sl = $("#fAsof"); sl.max = months.length - 1; sl.value = months.length - 1; cfg.asof = months.at(-1).toISOString().slice(0, 10);
  $("#fFrom").innerHTML = Array.from({ length: end.getFullYear() - y0 + 1 }, (_, i) => `<option value="${y0 + i}-01-01">${y0 + i}</option>`).join("");
  buildChips();
  $("#fFrom").onchange = (e) => { cfg.from = e.target.value; reload(); };
  sl.oninput = () => { cfg.asof = months[sl.value].toISOString().slice(0, 10); $("#asofLabel").textContent = fmtDate(cfg.asof); reload(); };
  $("#asofLabel").textContent = fmtDate(cfg.asof);
  $("#btnReset").onclick = () => location.reload();
  $("#btnRefresh").onclick = refreshLive;
  $("#btnTheme").textContent = "Theme"; $("#btnTheme").onclick = () => { const r = document.documentElement; r.dataset.theme = isDark() ? "light" : "dark"; if (D) render(); };
  $("#drawerClose").onclick = () => ($("#drawer").hidden = true);
  $$("#tabs button").forEach((b) => (b.onclick = () => { $$("#tabs button").forEach((x) => x.classList.toggle("on", x === b)); $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + b.dataset.tab)); if (D) render(); }));
  await reload();
}

function buildChips() {
  $("#chipsComp").innerHTML = CFG.competitors.map((c, i) => `<button class="chip" data-k="comp" data-v="${c.id}" aria-pressed="true">${swatch(c.id, c.color)}${esc(c.short)}</button>`).join("");
  $("#chipsPhase").innerHTML = CFG.phases.map((p) => `<button class="chip" data-k="phase" data-v="${p.id}" aria-pressed="true" title="${esc(p.blurb)}">${p.id}. ${esc(p.name)}</button>`).join("");
  $("#chipsType").innerHTML = CFG.event_types.map((t) => `<button class="chip" data-k="type" data-v="${t}" aria-pressed="true">${t}</button>`).join("");
  $$(".chip").forEach((b) => (b.onclick = () => {
    const on = b.getAttribute("aria-pressed") === "true"; b.setAttribute("aria-pressed", String(!on));
    const k = b.dataset.k, v = k === "phase" ? +b.dataset.v : b.dataset.v;
    const key = { comp: "competitors", phase: "phases", type: "types" }[k];
    cfg[key] = on ? cfg[key].filter((x) => x !== v) : [...cfg[key], v];
    reload();
  }));
}

function reload() { clearTimeout(timer); timer = setTimeout(async () => { try { D = await api("/api/dashboard", cfg); render(); } catch (e) { console.error(e); } }, 90); return Promise.resolve(); }

/* ---------------------------------------------------------------- live scrape */
async function refreshLive() {
  const btn = $("#btnRefresh"), dr = $("#drawer"), body = $("#drawerBody");
  btn.disabled = true; btn.textContent = "Scraping…"; $("#liveDot").className = "dot busy"; dr.hidden = false; body.innerHTML = "<p class='muted'>Starting scrapers…</p>";
  try {
    const res = await fetch("/api/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ live: LIVE }) });
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "", total = 0, okc = 0, seen = 0;
    while (true) {
      const { value, done } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); const lines = buf.split("\n"); buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue; const ev = JSON.parse(line);
        if (ev.event === "start") { total = ev.total; body.innerHTML = `<p class="muted small" id="prog">0 / ${total} sources</p>` + ev.sources.map((s) => `<div class="src" data-s="${esc(s)}"><span class="faint">…</span><span>${esc(s)}</span><span class="ms"></span></div>`).join(""); }
        if (ev.event === "source") { seen++; if (ev.ok) okc++; const row = [...body.querySelectorAll(".src")].find((r) => r.dataset.s === ev.source); if (row) { row.children[0].innerHTML = ev.ok ? "<span style='color:var(--ok)'>✓</span>" : "<span style='color:var(--bad)'>✕</span>"; row.children[2].textContent = ev.ms + " ms"; if (ev.error) row.insertAdjacentHTML("beforeend", `<span class="err">${esc(ev.error)}</span>`); } $("#prog").textContent = `${seen} / ${total} sources`; }
        if (ev.event === "done") { if (ev.history) { LIVE = ev.history; cfg.live = LIVE; try { localStorage.setItem("spot_ci_live", JSON.stringify(LIVE)); } catch (e) { /* storage may be blocked */ } } body.insertAdjacentHTML("beforeend", `<p style="margin-top:10px"><b>${ev.ok} of ${ev.total} sources parsed.</b> Failed sources keep their last known values.</p>` + (ev.notes.length ? "<p class='small muted'>" + ev.notes.map(esc).join("<br>") + "</p>" : "")); }
      }
    }
  } catch (e) { body.insertAdjacentHTML("beforeend", `<p style="color:var(--bad)">Refresh failed: ${esc(e.message)}. Showing last known data.</p>`); }
  btn.disabled = false; btn.textContent = "Refresh live data"; D = await api("/api/dashboard", cfg); render();
}

/* ---------------------------------------------------------------- render */
function render() {
  setLive(); renderOverview(); renderGrowth(); renderJourney(); renderGaps(); renderRoadmap(); renderRevenue(); renderEvidence();
}
function setLive() {
  const m = D.meta, ok = (m.log || []).filter((x) => x.ok).length;
  $("#liveDot").className = "dot" + (m.last_refresh && ok ? " ok" : "");
  $("#liveText").textContent = !m.last_refresh ? "Researched seed data · 9 Oct 2026" : ok ? `Live scrape ${ago(m.last_refresh)} · ${ok}/${m.log.length} sources OK` : `Last scrape reached 0/${m.log.length} sources · showing seed data`;
}
const ago = (iso) => { const s = (Date.now() - new Date(iso)) / 1000; return s < 90 ? "just now" : s < 5400 ? Math.round(s / 60) + " min ago" : s < 129600 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " d ago"; };
const statusTag = (s) => `<span class="tag ${s === "Active" ? "ok" : s === "Dormant" ? "bad" : s === "Slowing" ? "warn" : ""}">${esc(s)}</span>`;
const qualTag = (q) => `<span class="tag ${q === "high" ? "ok" : q === "low" ? "bad" : "warn"}">${q} evidence</span>`;
function killChart(k) { if (charts[k]) { charts[k].destroy(); delete charts[k]; } }

function renderOverview() {
  const el = $("#tab-overview");
  const sel = D.cards.filter((c) => c.selected);
  const seenT = new Set(), top = [...D.steps].sort((a, b) => b.score - a.score).filter((x) => (seenT.has(x.type) ? false : seenT.add(x.type))).slice(0, 3);
  el.innerHTML = `
  <div class="grid g4">${D.insights.map((i) => `<div class="card kpi"><div class="l">${esc(i.label)}</div><div class="v">${esc(i.value)}</div><div class="small muted">${esc(i.sub)}</div></div>`).join("")}</div>
  <div class="sec-h"><div><h2>Competitors as of ${fmtDate(D.asof)}</h2><span class="muted small">Growth index blends reach, footprint, release momentum, recency and review volume (0 to 100). Hover a bar for the parts.</span></div></div>
  <div class="card tbl-wrap"><table><thead><tr><th>Competitor</th><th>Phase</th><th>Status</th><th>Growth index</th><th class="num">Reach</th><th class="num">Rating</th><th>Last release</th><th>Evidence</th></tr></thead><tbody>
  ${sel.map((c) => `<tr><td><div class="name">${swatch(c.id, colorOf(c))}${esc(c.short)}</div><div class="small muted">${esc(c.kind)} · ${esc(c.geo)}</div></td>
    <td><span class="tag">${c.phase ? c.phase + ". " : ""}${esc(c.phase_name)}</span></td>
    <td>${statusTag(c.status)}${c.months_since_release != null ? `<div class="small faint">${c.months_since_release} mo ago</div>` : ""}</td>
    <td title="${Object.entries(c.growth_parts).map(([k, v]) => k + " " + v).join(" · ")}"><div style="display:flex;gap:8px;align-items:center"><b>${c.growth_index}</b><div class="bar" style="width:110px"><i style="width:${c.growth_index}%;background:${colorOf(c)}"></i></div></div></td>
    <td class="num">${compact(c.reach)}<div class="small faint">${esc(c.reach_kind || "no data")}</div></td>
    <td class="num">${c.rating ?? "n/a"}${c.reviews ? `<div class="small faint">${compact(c.reviews)} reviews</div>` : ""}</td>
    <td>${c.last_release ? fmtDate(c.last_release) : "n/a"}</td><td>${qualTag(c.evidence_quality)}</td></tr>`).join("")}
  </tbody></table></div>
  <div class="sec-h"><div><h2>Three moves that matter most right now</h2><span class="muted small">Highest-scoring rules from the recommender. Full plan in the roadmap tab.</span></div></div>
  <div class="grid g4">${top.map((s) => stepCard(s)).join("")}</div>`;
}

function stepCard(s) {
  return `<article class="step t-${s.type}"><span class="tag">${TYPE_LABEL[s.type]} · Phase ${s.phase}</span><h4>${esc(s.title)}</h4><p>${esc(s.action)}</p>
  <div class="row"><b>Why:</b> <span class="muted">${esc(s.why)}</span></div>
  <div class="row"><b>KPI:</b> <span class="muted">${esc(s.kpi)}</span></div>
  <div class="row"><b>Revenue link:</b> <span class="muted">${esc(s.revenue)}</span></div>
  <details><summary>Evidence and trigger</summary>${s.evidence.map((e) => `<span class="ev-chip"><b>${esc(e.who)}</b> ${esc(e.fact)}</span>`).join("")}<div class="small faint" style="margin-top:6px">Rule ${esc(s.rule)} · ${esc(s.trigger)}</div></details></article>`;
}

function renderGrowth() {
  const el = $("#tab-growth");
  const legend = (arr) => `<div class="legend">${arr.map((s) => `<span>${swatch(s.id, colorOf(D.cards.find((c) => c.id === s.id)))}${esc(s.short)}</span>`).join("")}</div>`;
  const noReach = D.reach_series.filter((s) => !s.points.length).map((s) => s.short);
  el.innerHTML = `<div class="grid g2">
   <div class="card"><h2>Reach over time</h2><p class="muted small">Users, installs or downloads on a log scale. Each point is a dated observation; kinds differ by source (hover).</p>${legend(D.reach_series)}<div class="chartbox"><canvas id="chReach" aria-label="Reach over time chart"></canvas></div>${noReach.length ? `<p class="small faint">No reach data yet: ${esc(noReach.join(", "))}.</p>` : ""}</div>
   <div class="card"><h2>Release momentum</h2><p class="muted small">Cumulative launches, features, policy moves and milestones. A flat line means the product has stopped moving.</p>${legend(D.momentum)}<div class="chartbox"><canvas id="chMom" aria-label="Release momentum chart"></canvas></div></div></div>
  <div class="sec-h"><div><h2>Event feed</h2><span class="muted small">${D.events.length} events match your filters. Live news and store updates appear here after a refresh.</span></div></div>
  <div class="card feed">${D.events.length ? D.events.map((e) => `<div class="ev"><div class="d">${fmtDate(e.date, e.precision)}</div><div><b>${esc(e.title)}</b><div class="small muted">${esc(e.detail)}</div><div class="meta"><span class="name" style="font-weight:500">${swatch(e.competitor, colorOf(D.cards.find((c) => c.id === e.competitor)))}${esc(e.short)}</span><span class="tag">${e.type}</span><span class="tag">phase ${e.phase}</span>${e.conf !== "high" ? `<span class="tag warn">${e.conf} confidence</span>` : ""}${e.url ? `<a class="small" href="${esc(e.url)}" target="_blank" rel="noopener">source</a>` : ""}</div></div></div>`).join("") : `<p class="muted">No events in this window. Widen the timeline or phase filters.</p>`}</div>`;
  const tc = cssv("--muted"), gc = cssv("--line");
  const base = { responsive: true, maintainAspectRatio: false, interaction: { mode: "nearest", intersect: true }, plugins: { legend: { display: false } },
    scales: { x: { type: "linear", min: +D.from.slice(0, 4), max: +D.asof.slice(0, 4) + 0.9, ticks: { callback: (v) => (Number.isInteger(v) ? v : ""), color: tc, maxRotation: 0, autoSkip: true, maxTicksLimit: 8 }, grid: { color: gc } }, y: { grid: { color: gc }, ticks: { color: tc } } } };
  killChart("reach"); killChart("mom");
  charts.reach = new Chart($("#chReach"), { type: "line", data: { datasets: D.reach_series.filter((s) => s.points.length).map((s) => ({ label: s.short, data: s.points, borderColor: colorOf(D.cards.find((c) => c.id === s.id)), backgroundColor: colorOf(D.cards.find((c) => c.id === s.id)), borderWidth: 2, pointStyle: SHAPES[idx(s.id) % 6][0], pointRadius: 6, pointHoverRadius: 8, tension: 0 })) },
    options: { ...base, parsing: false, scales: { ...base.scales, y: { ...base.scales.y, type: "logarithmic", min: 100, ticks: { color: tc, callback: (v) => ([100, 1e3, 1e4, 1e5, 1e6, 1e7].includes(v) ? compact(v) : "") } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.raw.y.toLocaleString("en-IN")} (${c.raw.kind}, ${c.raw.date})` } } } } });
  charts.mom = new Chart($("#chMom"), { type: "line", data: { datasets: D.momentum.filter((s) => s.points.length).map((s) => ({ label: s.short, data: s.points, borderColor: colorOf(D.cards.find((c) => c.id === s.id)), backgroundColor: colorOf(D.cards.find((c) => c.id === s.id)), borderWidth: 2, stepped: "after", pointStyle: SHAPES[idx(s.id) % 6][0], pointRadius: 4, pointHoverRadius: 7 })) },
    options: { ...base, parsing: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.raw.y} milestones · ${c.raw.title}` } } }, scales: { ...base.scales, y: { ...base.scales.y, beginAtZero: true, ticks: { color: tc, precision: 0 } } } } });
}

function renderJourney() {
  const el = $("#tab-journey");
  el.innerHTML = `<h2>Phase-by-phase journey</h2><p class="muted small">Where each competitor sits in the lifecycle, and the moves they made in each phase. The outlined cell is their current phase as of ${fmtDate(D.asof)}. Use this to see what they did to graduate, then copy the pattern, not the product.</p>
  <div class="card tbl-wrap"><div class="journey"><div></div>${D.phases.map((p) => `<div class="jh"><b>${p.id}. ${esc(p.name)}</b><small>${esc(p.blurb)}</small></div>`).join("")}
  ${D.journey.map((r) => `<div class="name" style="align-self:center">${swatch(r.id, colorOf(D.cards.find((c) => c.id === r.id)))}${esc(r.short)}</div>` + r.cells.map((c) => `<div class="jc ${c.n ? "" : "empty"} ${r.current === c.phase ? "cur" : ""}">${c.n ? `<b>${c.n}</b> move${c.n > 1 ? "s" : ""}<div class="faint">from ${fmtDate(c.first)}</div><div class="muted" style="margin-top:4px">${c.titles.map(esc).join("<br>")}</div>` : (r.current === c.phase ? "Current phase<br>(no dated moves)" : "no dated moves")}</div>`).join("")).join("")}</div></div>
  <div class="sec-h"><div><h2>How fast did they grow?</h2><span class="muted small">Users added per month between launch and the first observed reach point. These paces drive the Spot India projection.</span></div></div>
  <div class="grid g4">${D.cards.filter((c) => c.pace).map((c) => `<div class="card kpi"><div class="name">${swatch(c.id, colorOf(c))}${esc(c.short)}</div><div class="v">${compact(c.pace.per_month)}<span class="small muted"> / month</span></div><div class="small muted">${compact(c.pace.users)} ${esc(c.pace.kind)} in ${c.pace.months} months</div><div class="small faint">${c.id === "swachhata" ? "Programme-mandated burst" : c.id === "tracsha" ? "Dormant" : "Organic or slow-institutional"}</div></div>`).join("")}</div>`;
}

function renderGaps() {
  const el = $("#tab-gaps"), cs = D.cards.filter((c) => c.selected);
  const sym = (v, hint) => `<span class="dotm ${v >= 1 ? "full" : v > 0 ? "half" : hint ? "hint" : "none"}"></span>`;
  el.innerHTML = `<h2>Feature gap matrix</h2><p class="muted small"><span class="dotm full"></span> has it · <span class="dotm half"></span> partial · <span class="dotm none"></span> none · <span class="dotm hint"></span> keyword seen on live website (unconfirmed). Tick <b>Built</b> for what Spot India has shipped and the roadmap recomputes. The star marks your unique idea; rows where few competitors play are your whitespace.</p>
  <div class="card tbl-wrap"><table class="mx"><thead><tr><th>Feature</th><th>USP</th><th>Built</th>${cs.map((c) => `<th class="cell" style="text-align:center">${swatch(c.id, colorOf(c))}<br>${esc(c.short)}</th>`).join("")}<th>Adoption</th></tr></thead><tbody>
  ${D.matrix.map((m) => `<tr class="${m.usp ? "usp" : ""}"><td>${esc(m.name)}</td><td><input type="checkbox" data-usp="${m.id}" ${m.usp ? "checked" : ""} aria-label="Unique idea: ${esc(m.name)}"></td><td><input type="checkbox" data-built="${m.id}" ${m.built ? "checked" : ""} aria-label="Built: ${esc(m.name)}"></td>
    ${cs.map((c) => { const x = m.cells[c.id]; return `<td class="cell" title="${esc(x.note || (x.hint ? "Keyword detected on website (unconfirmed)" : "Not offered"))}" aria-label="${esc(c.short)}: ${x.v >= 1 ? "yes" : x.v > 0 ? "partial" : "no"}">${sym(x.v, x.hint)}</td>`; }).join("")}
    <td><div class="bar" style="width:90px"><i style="width:${m.share * 100}%;background:var(--ink)"></i></div><span class="small faint">${Math.round(m.share * 100)}%</span></td></tr>`).join("")}</tbody></table></div>`;
  $$("[data-built]", el).forEach((cb) => (cb.onchange = () => { cfg.built = cb.checked ? [...cfg.built, cb.dataset.built] : cfg.built.filter((x) => x !== cb.dataset.built); reload(); }));
  $$("[data-usp]", el).forEach((cb) => (cb.onchange = () => { cfg.usp = cb.checked ? [...cfg.usp, cb.dataset.usp] : cfg.usp.filter((x) => x !== cb.dataset.usp); reload(); }));
}

function renderRoadmap() {
  const el = $("#tab-roadmap");
  el.innerHTML = `<div class="sec-h" style="margin-top:0"><div><h2>What Spot India should do, phase by phase</h2><span class="muted small">Generated by rules over the live competitor data, so it changes when their moves, ratings or your built features change. Every step shows its evidence and the rule that fired.</span></div><button id="btnBrief" class="btn">Write owner briefing</button></div>
  <div id="brief" class="card brief" hidden></div>
  <div class="roadmap">${[1, 2, 3, 4, 5].map((p) => `<div class="col"><h3>Phase ${p} · ${SPOT_PH[p][0]}</h3><div class="when">${SPOT_PH[p][1]}</div>${D.steps.filter((s) => s.phase === p).map(stepCard).join("") || `<div class="note">No rule fired for this phase with the current filters.</div>`}</div>`).join("")}</div>`;
  $("#btnBrief").onclick = async () => { const b = $("#brief"); b.hidden = false; b.textContent = "Writing…"; try { const r = await api("/api/narrative", cfg); b.innerHTML = `<span class="tag">${r.source === "claude" ? "Written by Claude" : "Rule-based summary"}</span><p style="margin-top:8px">${esc(r.text)}</p>${r.note ? `<p class="small faint">${esc(r.note)}</p>` : ""}${CFG.llm ? "" : `<p class="small faint">Set ANTHROPIC_API_KEY on the server to get a Claude-written briefing.</p>`}`; } catch (e) { b.textContent = "Briefing failed: " + e.message; } };
}

function renderRevenue() {
  const el = $("#tab-revenue"), a = D.assumptions, r = D.revenue, p = r.paces;
  if (!revBuilt) {
    revBuilt = true;
    el.innerHTML = `<h2>Revenue path to the benchmark</h2><p class="muted small">None of these competitors publish revenue. This is a pricing scenario: the same formula is applied to their footprint and to Spot India's projected footprint, so the comparison is like for like. Change the assumptions and watch the parity month move.</p>
    <div class="card"><div style="display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:12px"><div><div class="lbl">Growth scenario</div><div class="seg" id="segScen">${[["organic", "Organic"], ["hybrid", "Hybrid"], ["b2g", "Government-led"]].map(([k, l]) => `<button data-s="${k}">${l}</button>`).join("")}</div></div><label class="f">Benchmark <select id="selBench">${CFG.competitors.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></label></div>
    <div class="ctrl" id="ctrl"></div></div>
    <div id="revOut"></div>`;
    $$("#segScen button").forEach((b) => (b.onclick = () => { cfg.assumptions.scenario = b.dataset.s; reload(); }));
    $("#selBench").onchange = (e) => { cfg.assumptions.benchmark = e.target.value; reload(); };
    const sl = [["arpu_ulb_lakh", "Licence per city or department (₹ lakh/yr)", .5, 25, .5], ["premium_conv_pct", "Users on a paid tier (%)", 0, 3, .1], ["arpu_user", "Price per paid user (₹/yr)", 100, 1200, 50], ["csr_lakh_per_100k", "CSR sponsorship per 100K users (₹ lakh/yr)", 0, 20, 1], ["pilot_month", "First paying pilot (month)", 3, 18, 1], ["ulb_adds", "New cities or departments per month", 0, 5, .1]];
    $("#ctrl").innerHTML = sl.map(([k, l, mn, mx, st]) => `<label>${l}<b id="v_${k}"></b><input type="range" data-k="${k}" min="${mn}" max="${mx}" step="${st}"></label>`).join("");
    $$("#ctrl input").forEach((i) => { i.oninput = () => { setAssump(i); $(`#v_${i.dataset.k}`).textContent = i.value; }; i.onchange = reload; });
  }
  $$("#segScen button").forEach((b) => b.classList.toggle("on", b.dataset.s === a.scenario));
  $("#selBench").value = a.benchmark;
  $$("#ctrl input").forEach((i) => { const k = i.dataset.k, v = k === "ulb_adds" ? a.ulb_adds[a.scenario] : a[k]; if (document.activeElement !== i) i.value = v; $(`#v_${k}`).textContent = i.value; });
  const bm = r.benchmark, rows = r.rows, stages = [6, 12, 24, 36, 48, 60].filter((m) => m <= rows.at(-1).m).map((m) => rows[m]);
  $("#revOut").innerHTML = `<div class="grid g4" style="margin-top:14px">
   <div class="card kpi"><div class="l">Parity with ${esc(bm.name)}</div><div class="v">${r.parity_month ? "Month " + r.parity_month : "Not in " + rows.at(-1).m + " months"}</div><div class="small muted">Benchmark worth ${inr(bm.total)} a year at your prices</div></div>
   <div class="card kpi"><div class="l">Users added per month</div><div class="v">${compact(r.per_month)}</div><div class="small muted">Organic ${compact(p.organic)} · Hybrid ${compact(p.hybrid)} · Mandated ${compact(p.mandated)}</div></div>
   <div class="card kpi"><div class="l">Benchmark footprint</div><div class="v">${compact(bm.users)} users</div><div class="small muted">${esc(bm.note)}</div></div>
   <div class="card kpi"><div class="l">Where the paces come from</div><div class="small muted" style="margin-top:6px">Organic: ${esc(p.organic_from.join(" + "))} averaged. Mandated: ${esc(p.mandated_from.join(", "))} first-year burst. Hybrid: midpoint.</div></div></div>
  <div class="card" style="margin-top:14px"><h2>Spot India annual revenue run-rate</h2><div class="legend"><span><i class="sw rect" style="background:var(--accent)"></i>Licences</span><span><i class="sw rect" style="background:color-mix(in srgb,var(--accent) 55%,transparent)"></i>CSR sponsorship</span><span><i class="sw rect" style="background:color-mix(in srgb,var(--accent) 25%,transparent)"></i>Paid tier</span><span><i class="sw rect" style="background:var(--ink)"></i>${esc(bm.short || bm.name)} benchmark</span></div><div class="chartbox tall"><canvas id="chRev" aria-label="Revenue projection chart"></canvas></div></div>
  <div class="card tbl-wrap" style="margin-top:14px"><table><thead><tr><th>Month</th><th class="num">Users</th><th class="num">Cities or depts</th><th class="num">Licences</th><th class="num">CSR</th><th class="num">Paid tier</th><th class="num">Run-rate</th><th class="num">% of benchmark</th></tr></thead><tbody>${stages.map((s) => `<tr><td>${s.m}</td><td class="num">${compact(s.users)}</td><td class="num">${s.ulb}</td><td class="num">${inr(s.licence)}</td><td class="num">${inr(s.csr)}</td><td class="num">${inr(s.premium)}</td><td class="num"><b>${inr(s.total)}</b></td><td class="num">${Math.round((s.total / bm.total) * 100)}%</td></tr>`).join("")}</tbody></table></div>
  <p class="note" style="margin-top:12px">Assumptions to defend in Q&A: the benchmark's city-equivalents are weights, not facts (${esc(bm.note)}); prices are yours to set; CSR and paid-tier lines are hypotheses to validate in interviews. Swachhata would be worth far more because it is in 4,503 cities, which no startup reaches without a national programme.</p>`;
  killChart("rev"); const tc = cssv("--muted"), gc = cssv("--line"), ac = cssv("--accent"), ink = cssv("--ink");
  const mix = (pct) => `color-mix(in srgb, ${ac} ${pct}%, transparent)`;
  charts.rev = new Chart($("#chRev"), { type: "line", data: { labels: rows.map((x) => x.m), datasets: [
    { label: "Licences", data: rows.map((x) => x.licence), backgroundColor: ac, borderColor: ac, fill: true, pointRadius: 0, borderWidth: 1.5, stack: "s" },
    { label: "CSR sponsorship", data: rows.map((x) => x.csr), backgroundColor: mix(55), borderColor: mix(55), fill: true, pointRadius: 0, borderWidth: 1.5, stack: "s" },
    { label: "Paid tier", data: rows.map((x) => x.premium), backgroundColor: mix(25), borderColor: mix(25), fill: true, pointRadius: 0, borderWidth: 1.5, stack: "s" },
    { label: "Benchmark", data: rows.map(() => bm.total), borderColor: ink, borderDash: [6, 4], borderWidth: 2, pointRadius: 0, fill: false } ] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { legend: { display: false }, tooltip: { callbacks: { title: (i) => "Month " + i[0].label, label: (c) => `${c.dataset.label}: ${inr(c.raw)}` } } },
      scales: { x: { title: { display: true, text: "Months since start", color: tc }, ticks: { color: tc, maxTicksLimit: 13 }, grid: { color: gc } }, y: { stacked: true, ticks: { color: tc, callback: (v) => inr(v) }, grid: { color: gc } } } } });
}
function setAssump(i) { const k = i.dataset.k, v = +i.value; if (k === "ulb_adds") cfg.assumptions.ulb_adds = { ...cfg.assumptions.ulb_adds, [cfg.assumptions.scenario]: v }; else cfg.assumptions[k] = v; }

function renderEvidence() {
  const el = $("#tab-evidence"), m = D.meta;
  el.innerHTML = `<h2>Fixes for your slide 7</h2><p class="muted small">Checked against primary pages on ${fmtDate(D.meta.last_refresh ? D.meta.last_refresh.slice(0, 10) : "2026-10-09")}. Fix these before you present, because an evaluator who checks will find them.</p>
  <div class="grid g2">${D.fact_checks.map((f) => `<div class="card"><span class="tag warn">${esc(f.slide)}</span><p style="margin-top:8px"><b>Claim:</b> ${esc(f.claim)}</p><p class="muted"><b>Found:</b> ${esc(f.finding)}</p><p><b>Fix:</b> ${esc(f.fix)}</p>${D.sources[f.src] && D.sources[f.src].url ? `<a class="small" href="${esc(D.sources[f.src].url)}" target="_blank" rel="noopener">${esc(D.sources[f.src].title)}</a>` : ""}</div>`).join("")}</div>
  <div class="sec-h"><div><h2>Business models observed</h2></div></div>
  <div class="card tbl-wrap"><table><thead><tr><th>Competitor</th><th>How it is funded or earns</th><th>Customers</th><th>Data quality</th></tr></thead><tbody>${D.cards.map((c) => `<tr><td><div class="name">${swatch(c.id, colorOf(c))}${esc(c.short)}</div><div class="small muted">${esc(c.owner)}</div></td><td>${c.business_model.map(esc).join("<br>")}</td><td class="muted">${esc(c.customers)}</td><td>${qualTag(c.evidence_quality)}<div class="small muted">${esc(c.evidence_note)}</div></td></tr>`).join("")}</tbody></table></div>
  <div class="sec-h"><div><h2>Latest scrape log</h2><span class="muted small">${m.last_refresh ? "Last run " + ago(m.last_refresh) : "No live run yet. Press Refresh live data."}</span></div></div>
  <div class="card">${(m.log || []).length ? (m.log).map((l) => `<div class="src"><span style="color:var(${l.ok ? "--ok" : "--bad"})">${l.ok ? "✓" : "✕"}</span><span>${esc(l.source)}</span><span class="ms">${l.ms} ms</span>${l.error ? `<span class="err">${esc(l.error)}</span>` : ""}</div>`).join("") : `<p class="muted">Scrapers: Play Store (BeautifulSoup), App Store (iTunes lookup), Google News RSS, competitor websites (profile and KPI extraction, change detection) and GitHub.</p>`}</div>
  <div class="sec-h"><div><h2>Sources</h2></div></div>
  <div class="card"><ul>${Object.values(D.sources).filter((s) => s.url).map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("")}</ul></div>`;
}

init();
})();
