const API_URL = "/api/market";
const state = {
  ipos: [], earlyGmp: [], sources: {}, overview: {}, meta: {}, generatedAt: null,
  query: "", earlyQuery: "", status: "all", platform: "all", savedOnly: false,
  sort: "openDate", direction: 1, compared: new Set(),
  saved: new Set(JSON.parse(localStorage.getItem("ipo-saved") || "[]")),
};
const $ = (selector) => document.querySelector(selector);
const money = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const numberFormat = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

function esc(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}
function safeUrl(value) { try { const url = new URL(value); return url.protocol === "https:" ? url.href : ""; } catch { return ""; } }
function number(value) { const match = String(value ?? "").replaceAll(",", "").match(/-?[\d.]+/); const parsed = match ? Number(match[0]) : NaN; return Number.isFinite(parsed) ? parsed : null; }
function date(value, full = false) { if (!value) return "—"; const parsed = new Date(`${value}T00:00:00`); return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleDateString("en-IN", full ? { day: "2-digit", month: "short", year: "numeric" } : { day: "2-digit", month: "short" }); }
function dateTime(value) { if (!value) return "—"; const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }); }
function band(value) { if (!value || value.max == null) return "—"; return value.min === value.max ? money.format(value.max) : `${money.format(value.min)}–${money.format(value.max)}`; }
function investment(ipo) { const lot = number(ipo.lotSize); return lot != null && ipo.priceBand?.max != null ? lot * ipo.priceBand.max : null; }
function gmpText(gmp) { if (!gmp || gmp.value == null) return "—"; const percent = gmp.percent == null ? "" : ` (${gmp.percent > 0 ? "+" : ""}${numberFormat.format(gmp.percent)}%)`; return `${money.format(gmp.value)}${percent}`; }
function valueOrDash(value) { return value == null || value === "" ? "—" : value; }
function companyKey(ipo) { return ipo.companyName; }

function renderStats() {
  const o = state.overview;
  const items = [
    ["All official issues", o.totalIssues, "Open + upcoming"], ["Open now", o.openIssues, "Accepting bids"],
    ["Upcoming", o.upcomingIssues, "Scheduled"], ["GMP quoted", o.quotedIssues, "Matched records"],
    ["Average GMP", o.averageGmpPercent == null ? "—" : `${o.averageGmpPercent}%`, "Quoted issues"],
    ["Disclosed capital", o.disclosedCapitalCrore ? `₹${numberFormat.format(o.disclosedCapitalCrore)} Cr` : "—", "Current issue set"],
    ["Early GMP", o.earlyGmpIssues, "Awaiting official match"],
  ];
  $("#stats").innerHTML = items.map(([label, value, note]) => `<div class="stat"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join("");
}

function renderSchedule() {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const events = state.ipos.flatMap((ipo) => [["Opens", ipo.openDate], ["Closes", ipo.closeDate], ["Lists", ipo.listingDate]].filter(([, d]) => d).map(([event, d]) => ({ ipo, event, date: d, time: new Date(`${d}T00:00:00`) })))
    .filter((event) => event.time >= today).sort((a, b) => a.time - b.time).slice(0, 12);
  $("#schedule-body").innerHTML = events.length ? events.map((event) => { const days = Math.round((event.time - today) / 86400000); return `<tr><td><button class="company-button" data-company="${esc(companyKey(event.ipo))}">${esc(event.ipo.companyName)}</button></td><td>${esc(event.event)}</td><td class="numeric">${esc(date(event.date, true))}</td><td>${days === 0 ? "Today" : `${days}d`}</td></tr>`; }).join("") : `<tr class="empty-row"><td colspan="4">No scheduled events in the current dataset</td></tr>`;
}

function renderSignals() {
  const rows = [...state.ipos].filter((ipo) => ipo.gmp?.value != null && ipo.gmp?.percent != null).sort((a, b) => b.gmp.percent - a.gmp.percent).slice(0, 7);
  $("#signal-list").innerHTML = rows.length ? rows.map((ipo, index) => `<div class="signal-item"><span>${String(index + 1).padStart(2, "0")}</span><div><button class="company-button" data-company="${esc(companyKey(ipo))}">${esc(ipo.companyName)}</button><small>${esc(ipo.platform || "Platform pending")} · ${esc(valueOrDash(ipo.subscriptionTimes))} subscribed</small></div><span class="signal-value ${ipo.gmp.percent >= 0 ? "positive" : "negative"}">${ipo.gmp.percent > 0 ? "+" : ""}${esc(numberFormat.format(ipo.gmp.percent))}%</span></div>`).join("") : `<div class="empty-row"><p>No GMP signals available</p></div>`;
}

function filteredIpos() {
  const q = state.query.toLowerCase().trim();
  const list = state.ipos.filter((ipo) => (!q || ipo.companyName.toLowerCase().includes(q)) && (state.status === "all" || ipo.status === state.status) && (state.platform === "all" || ipo.platform === state.platform) && (!state.savedOnly || state.saved.has(companyKey(ipo))));
  const getters = { companyName: (i) => i.companyName.toLowerCase(), status: (i) => i.status || "", openDate: (i) => i.openDate || "9999", investment: (i) => investment(i) ?? Infinity, gmp: (i) => i.gmp?.percent ?? -Infinity, subscription: (i) => number(i.subscriptionTimes) ?? -Infinity };
  const get = getters[state.sort];
  return list.sort((a, b) => { const av = get(a), bv = get(b); return (typeof av === "string" ? av.localeCompare(bv) : av - bv) * state.direction; });
}

function renderIssues() {
  const rows = filteredIpos();
  $("#result-count").textContent = `${rows.length} ${rows.length === 1 ? "issue" : "issues"}`;
  $("#issues-body").innerHTML = rows.length ? rows.map((ipo) => {
    const key = companyKey(ipo), min = investment(ipo), percent = ipo.gmp?.percent;
    return `<tr><td><button class="star ${state.saved.has(key) ? "saved" : ""}" data-save="${esc(key)}" aria-label="Save ${esc(ipo.companyName)}">★</button></td>
      <td><button class="company-button" data-company="${esc(key)}">${esc(ipo.companyName)}</button><span class="subtext">${esc(ipo.platform || "Platform pending")}</span></td>
      <td><span class="pill ${esc(ipo.status)}">${esc(ipo.status || "pending")}</span></td><td>${esc(ipo.exchanges?.join(" + ") || "—")}</td>
      <td class="numeric">${esc(date(ipo.openDate))} → ${esc(date(ipo.closeDate))}<span class="subtext">Lists ${esc(date(ipo.listingDate))}</span></td>
      <td class="numeric">${esc(band(ipo.priceBand))}<span class="subtext">${esc(valueOrDash(ipo.lotSize))} shares / lot</span></td>
      <td class="numeric">${min == null ? "—" : esc(money.format(min))}</td>
      <td class="numeric ${percent == null ? "" : percent >= 0 ? "positive" : "negative"}">${esc(gmpText(ipo.gmp))}<span class="subtext">${esc(valueOrDash(ipo.gmpUpdatedOn))}</span></td>
      <td class="numeric">${esc(valueOrDash(ipo.subscriptionTimes))}</td><td><input class="compare-check" data-compare="${esc(key)}" type="checkbox" aria-label="Compare ${esc(ipo.companyName)}" ${state.compared.has(key) ? "checked" : ""}></td></tr>`;
  }).join("") : `<tr class="empty-row"><td colspan="10">No issues match these filters</td></tr>`;
}

function renderEarly() {
  const q = state.earlyQuery.toLowerCase().trim();
  const rows = state.earlyGmp.filter((row) => !q || row.companyName?.toLowerCase().includes(q));
  $("#early-body").innerHTML = rows.length ? rows.map((row) => { const url = safeUrl(row.detailUrl); const percent = row.gmp?.percent; return `<tr><td><strong>${esc(valueOrDash(row.companyName))}</strong></td><td><span class="pill ${esc(row.status)}">${esc(valueOrDash(row.status))}</span><span class="subtext">${esc(valueOrDash(row.category))}</span></td><td class="numeric">${esc(date(row.openDate))} → ${esc(date(row.closeDate))}<span class="subtext">Lists ${esc(date(row.listingDate))}</span></td><td>${esc(valueOrDash(row.price))}<span class="subtext">Lot ${esc(valueOrDash(row.lotSize))}</span></td><td>${esc(valueOrDash(row.issueSize))}</td><td class="${percent == null ? "" : percent >= 0 ? "positive" : "negative"}">${esc(gmpText(row.gmp))}</td><td>${esc(valueOrDash(row.subscriptionTimes))}</td><td>${esc(valueOrDash(row.updatedOn))}</td><td>${url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">Open ↗</a>` : "—"}</td></tr>`; }).join("") : `<tr class="empty-row"><td colspan="9">No early GMP records match</td></tr>`;
}

function renderSources() {
  const labels = { nse: "NSE", bse: "BSE", investorGain: "InvestorGain" };
  $("#source-list").innerHTML = Object.entries(state.sources).map(([key, source]) => `<div class="source-row ${source.ok ? "" : "bad"}"><div><strong><i></i>${esc(labels[key] || key)} · ${source.ok ? "Operational" : "Degraded"}</strong><p>${esc(source.error || "Provider returned normally")}</p></div><span>${esc(source.recordCount ?? 0)} records</span></div>`).join("");
  const rows = [["Delivery", state.meta.delivery], ["Dataset generated", dateTime(state.generatedAt)], ["Response served", dateTime(state.meta.servedAt)], ["Process cache", `${state.meta.cacheTtlSeconds ?? 0} seconds`], ["API endpoint", API_URL]];
  $("#response-meta").innerHTML = rows.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(valueOrDash(value))}</dd></div>`).join("");
}

function showDetail(ipo) {
  const min = investment(ipo); const estimate = ipo.priceBand?.max != null && ipo.gmp?.value != null ? ipo.priceBand.max + ipo.gmp.value : null; const url = safeUrl(ipo.detailUrl);
  const fields = [["Status", ipo.status], ["Platform", ipo.platform], ["Exchanges", ipo.exchanges?.join(" + ")], ["Open date", date(ipo.openDate, true)], ["Close date", date(ipo.closeDate, true)], ["Listing date", date(ipo.listingDate, true)], ["Price band", band(ipo.priceBand)], ["Lot size", ipo.lotSize], ["Minimum bid", min == null ? null : money.format(min)], ["Face value", ipo.faceValue == null ? null : money.format(ipo.faceValue)], ["Issue size", ipo.issueSize], ["GMP", gmpText(ipo.gmp)], ["Estimated listing", estimate == null ? null : money.format(estimate)], ["Subscription", ipo.subscriptionTimes], ["GMP updated", ipo.gmpUpdatedOn]];
  $("#detail-content").innerHTML = `<div class="dialog-header"><h2>${esc(ipo.companyName)}</h2><p>Complete normalized API record</p></div><div class="detail-grid">${fields.map(([label, value]) => `<div class="detail"><span>${esc(label)}</span><strong>${esc(valueOrDash(value))}</strong></div>`).join("")}</div><div class="dialog-foot"><span>Estimated listing = upper price band + current GMP; it is not a forecast.</span>${url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">InvestorGain source ↗</a>` : ""}</div>`;
  $("#detail-dialog").showModal();
}

function renderCompareTray() {
  const selected = state.ipos.filter((ipo) => state.compared.has(companyKey(ipo)));
  $("#compare-tray").hidden = !selected.length; $("#compare-count").textContent = selected.length;
  $("#compare-names").innerHTML = selected.map((ipo) => `<span>${esc(ipo.companyName)}</span>`).join("");
  $("#open-compare").disabled = selected.length < 2;
}
function showComparison() {
  const selected = state.ipos.filter((ipo) => state.compared.has(companyKey(ipo)));
  const fields = [["Status", (i) => i.status], ["Platform", (i) => i.platform], ["Exchange", (i) => i.exchanges?.join(" + ")], ["Bid dates", (i) => `${date(i.openDate)} – ${date(i.closeDate)}`], ["Listing", (i) => date(i.listingDate)], ["Price band", (i) => band(i.priceBand)], ["Lot size", (i) => i.lotSize], ["Minimum bid", (i) => investment(i) == null ? null : money.format(investment(i))], ["Face value", (i) => i.faceValue == null ? null : money.format(i.faceValue)], ["Issue size", (i) => i.issueSize], ["GMP", (i) => gmpText(i.gmp)], ["Subscription", (i) => i.subscriptionTimes], ["GMP updated", (i) => i.gmpUpdatedOn]];
  $("#compare-content").innerHTML = `<div class="dialog-header"><h2>IPO comparison</h2><p>Side-by-side normalized data</p></div><div class="table-wrap"><table class="compare-table"><thead><tr><th>Metric</th>${selected.map((i) => `<th>${esc(i.companyName)}</th>`).join("")}</tr></thead><tbody>${fields.map(([label, get]) => `<tr><td>${esc(label)}</td>${selected.map((i) => `<td>${esc(valueOrDash(get(i)))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  $("#compare-dialog").showModal();
}

function renderAll() {
  $("#issues-count").textContent = state.ipos.length; $("#early-count").textContent = state.earlyGmp.length;
  renderStats(); renderSchedule(); renderSignals(); renderIssues(); renderEarly(); renderSources(); renderCompareTray();
}

async function loadData(refresh = false) {
  const button = $("#refresh"); const sync = $("#sync-state"); button.disabled = true; sync.className = "sync-state"; sync.innerHTML = "<i></i> Synchronizing"; $("#error-banner").hidden = true;
  try {
    const response = await fetch(refresh ? "/api/refresh" : API_URL, { method: refresh ? "POST" : "GET", cache: "no-store", headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const data = await response.json(); if (!Array.isArray(data.ipos) || !Array.isArray(data.earlyGmp)) throw new Error("API returned an invalid market payload");
    Object.assign(state, { ipos: data.ipos, earlyGmp: data.earlyGmp, sources: data.sources || {}, overview: data.overview || {}, meta: data.meta || {}, generatedAt: data.generatedAt });
    sync.className = "sync-state ok"; sync.innerHTML = `<i></i> ${data.meta?.delivery === "snapshot" ? "Snapshot fallback" : "API online"}`; $("#updated-at").textContent = `Generated ${dateTime(data.generatedAt)}`; renderAll();
  } catch (error) {
    sync.className = "sync-state error"; sync.innerHTML = "<i></i> API unavailable"; $("#error-banner").hidden = false; $("#error-banner").textContent = `${error.message}. The app does not read the JSON snapshot directly; verify the backend is running.`;
  } finally { button.disabled = false; }
}

document.addEventListener("click", (event) => {
  const tab = event.target.closest("[data-view]"); if (tab) { document.querySelectorAll("[data-view]").forEach((b) => b.classList.toggle("active", b === tab)); document.querySelectorAll("[data-panel]").forEach((p) => p.classList.toggle("active", p.dataset.panel === tab.dataset.view)); }
  const company = event.target.closest("[data-company]")?.dataset.company; if (company) { const ipo = state.ipos.find((item) => companyKey(item) === company); if (ipo) showDetail(ipo); }
  const saved = event.target.closest("[data-save]")?.dataset.save; if (saved) { state.saved.has(saved) ? state.saved.delete(saved) : state.saved.add(saved); localStorage.setItem("ipo-saved", JSON.stringify([...state.saved])); renderIssues(); }
  const sort = event.target.closest("[data-sort]")?.dataset.sort; if (sort) { state.direction = state.sort === sort ? state.direction * -1 : 1; state.sort = sort; renderIssues(); }
  const closer = event.target.closest("[data-close]"); if (closer) document.getElementById(closer.dataset.close).close();
});
$("#issues-body").addEventListener("change", (event) => { const key = event.target.dataset.compare; if (!key) return; if (event.target.checked && state.compared.size >= 3) { event.target.checked = false; return; } event.target.checked ? state.compared.add(key) : state.compared.delete(key); renderCompareTray(); });
$("#search").addEventListener("input", (e) => { state.query = e.target.value; renderIssues(); });
$("#early-search").addEventListener("input", (e) => { state.earlyQuery = e.target.value; renderEarly(); });
$("#status-filter").addEventListener("change", (e) => { state.status = e.target.value; renderIssues(); });
$("#platform-filter").addEventListener("change", (e) => { state.platform = e.target.value; renderIssues(); });
$("#saved-filter").addEventListener("change", (e) => { state.savedOnly = e.target.checked; renderIssues(); });
$("#refresh").addEventListener("click", () => loadData(true));
$("#clear-compare").addEventListener("click", () => { state.compared.clear(); renderIssues(); renderCompareTray(); });
$("#open-compare").addEventListener("click", showComparison);
$("#export-csv").addEventListener("click", () => { const headers = ["Company", "Status", "Platform", "Exchanges", "Open", "Close", "Listing", "Price min", "Price max", "Lot", "Minimum bid", "Face value", "Issue size", "GMP", "GMP percent", "Subscription", "GMP updated", "Detail URL"]; const values = filteredIpos().map((i) => [i.companyName, i.status, i.platform, i.exchanges?.join(" + "), i.openDate, i.closeDate, i.listingDate, i.priceBand?.min, i.priceBand?.max, i.lotSize, investment(i), i.faceValue, i.issueSize, i.gmp?.value, i.gmp?.percent, i.subscriptionTimes, i.gmpUpdatedOn, i.detailUrl]); const csv = [headers, ...values].map((row) => row.map((v) => `"${String(v ?? "").replaceAll('"', '""')}"`).join(",")).join("\n"); const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); link.download = "ipo-market.csv"; link.click(); URL.revokeObjectURL(link.href); });
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }));
loadData();
