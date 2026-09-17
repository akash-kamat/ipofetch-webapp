const API_URL = "/api/market";
const AUTO_REFRESH_MS = 15 * 60 * 1000;
const state = {
  ipos: [], earlyGmp: [], sources: {}, overview: {}, meta: {}, generatedAt: null,
  query: "", earlyQuery: "", status: "all", platform: "all", savedOnly: false,
  sort: "openDate", direction: -1, compared: new Set(),
  loading: false, loaded: false, lastLoadedAt: 0, currentDetail: null,
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
function subscriptionTimes(ipo) { return ipo.subscription?.totalTimes ?? null; }
function subscriptionText(ipo) { const value = subscriptionTimes(ipo); return value == null ? "—" : `${numberFormat.format(value)}x`; }
function valueOrDash(value) { return value == null || value === "" ? "—" : value; }
function companyKey(ipo) { return ipo.issueKey || ipo.companyName; }
function skeletonLine(width = "100%") { return `<span class="skeleton-line" style="width:${width}"></span>`; }

function renderSkeletons() {
  document.body.classList.add("is-loading");
  document.querySelector("main").setAttribute("aria-busy", "true");
  $("#stats").innerHTML = Array.from({ length: 8 }, () => `<div class="stat skeleton-card">${skeletonLine("55%")}<strong>${skeletonLine("38%")}</strong>${skeletonLine("70%")}</div>`).join("");
  $("#schedule-body").innerHTML = Array.from({ length: 6 }, () => `<tr class="skeleton-row"><td>${skeletonLine("78%")}</td><td>${skeletonLine("55px")}</td><td>${skeletonLine("80px")}</td><td>${skeletonLine("35px")}</td></tr>`).join("");
  $("#signal-list").innerHTML = Array.from({ length: 6 }, (_, index) => `<div class="signal-item skeleton-signal"><span>${String(index + 1).padStart(2, "0")}</span><div>${skeletonLine("72%")} ${skeletonLine("46%")}</div>${skeletonLine("48px")}</div>`).join("");
  $("#issues-body").innerHTML = Array.from({ length: 7 }, () => `<tr class="skeleton-row"><td>${skeletonLine("18px")}</td><td>${skeletonLine("150px")}</td><td>${skeletonLine("58px")}</td><td>${skeletonLine("45px")}</td><td>${skeletonLine("105px")}</td><td>${skeletonLine("90px")}</td><td>${skeletonLine("75px")}</td><td>${skeletonLine("70px")}</td><td>${skeletonLine("65px")}</td><td>${skeletonLine("18px")}</td></tr>`).join("");
  $("#early-body").innerHTML = Array.from({ length: 5 }, () => `<tr class="skeleton-row"><td>${skeletonLine("140px")}</td><td>${skeletonLine("80px")}</td><td>${skeletonLine("100px")}</td><td>${skeletonLine("80px")}</td><td>${skeletonLine("65px")}</td><td>${skeletonLine("55px")}</td><td>${skeletonLine("70px")}</td><td>${skeletonLine("45px")}</td></tr>`).join("");
  $("#source-list").innerHTML = Array.from({ length: 3 }, () => `<div class="source-row skeleton-source"><div>${skeletonLine("125px")}${skeletonLine("180px")}</div>${skeletonLine("65px")}</div>`).join("");
  $("#response-meta").innerHTML = Array.from({ length: 5 }, () => `<div><dt>${skeletonLine("85px")}</dt><dd>${skeletonLine("120px")}</dd></div>`).join("");
}

function renderStats() {
  const o = state.overview;
  const items = [
    ["All official issues", o.totalIssues, "Including 12-month history"], ["Open now", o.openIssues, "Accepting bids"],
    ["Upcoming", o.upcomingIssues, "Scheduled"], ["Closed", o.closedIssues, "Last 12 months"],
    ["GMP quoted", o.quotedIssues, "Matched records"], ["Average GMP", o.averageGmpPercent == null ? "—" : `${o.averageGmpPercent}%`, "Quoted issues"],
    ["Disclosed capital", o.disclosedCapitalCrore ? `₹${numberFormat.format(o.disclosedCapitalCrore)} Cr` : "—", "Current issue set"],
    ["Early GMP", o.earlyGmpIssues, "Awaiting official match"],
  ];
  $("#stats").innerHTML = items.map(([label, value, note]) => `<div class="stat"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join("");
}

function renderSchedule() {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const events = state.ipos.flatMap((ipo) => [["Opens", ipo.openDate], ["Closes", ipo.closeDate], ["Lists", ipo.listingDate]].filter(([, day]) => day).map(([event, day]) => ({ ipo, event, date: day, time: new Date(`${day}T00:00:00`) })))
    .filter((event) => event.time >= today).sort((a, b) => a.time - b.time).slice(0, 12);
  $("#schedule-body").innerHTML = events.length ? events.map((event) => { const days = Math.round((event.time - today) / 86400000); return `<tr><td data-label="Company"><button class="company-button" data-company="${esc(companyKey(event.ipo))}">${esc(event.ipo.companyName)}</button></td><td data-label="Event">${esc(event.event)}</td><td data-label="Date" class="numeric">${esc(date(event.date, true))}</td><td data-label="In">${days === 0 ? "Today" : `${days}d`}</td></tr>`; }).join("") : `<tr class="empty-row"><td colspan="4">No scheduled events in the current dataset</td></tr>`;
}

function renderSignals() {
  const rows = [...state.ipos].filter((ipo) => ipo.status !== "closed" && ipo.gmp?.value != null && ipo.gmp?.percent != null).sort((a, b) => b.gmp.percent - a.gmp.percent).slice(0, 7);
  $("#signal-list").innerHTML = rows.length ? rows.map((ipo, index) => `<div class="signal-item"><span>${String(index + 1).padStart(2, "0")}</span><div><button class="company-button" data-company="${esc(companyKey(ipo))}">${esc(ipo.companyName)}</button><small>${esc(ipo.platform || "Platform pending")} · ${esc(subscriptionText(ipo))} subscribed</small></div><span class="signal-value ${ipo.gmp.percent >= 0 ? "positive" : "negative"}">${ipo.gmp.percent > 0 ? "+" : ""}${esc(numberFormat.format(ipo.gmp.percent))}%</span></div>`).join("") : `<div class="empty-state">No GMP signals available</div>`;
}

function filteredIpos() {
  const query = state.query.toLowerCase().trim();
  const list = state.ipos.filter((ipo) => (!query || ipo.companyName.toLowerCase().includes(query)) && (state.status === "all" || ipo.status === state.status) && (state.platform === "all" || ipo.platform === state.platform) && (!state.savedOnly || state.saved.has(companyKey(ipo))));
  const getters = { companyName: (item) => item.companyName.toLowerCase(), status: (item) => item.status || "", openDate: (item) => item.openDate || "9999", investment: (item) => investment(item) ?? Infinity, gmp: (item) => item.gmp?.percent ?? -Infinity, subscription: (item) => subscriptionTimes(item) ?? -Infinity };
  const get = getters[state.sort];
  return list.sort((a, b) => { const first = get(a), second = get(b); return (typeof first === "string" ? first.localeCompare(second) : first - second) * state.direction; });
}

function renderIssues() {
  const rows = filteredIpos();
  $("#result-count").textContent = `${rows.length} ${rows.length === 1 ? "issue" : "issues"}`;
  $("#issues-body").innerHTML = rows.length ? rows.map((ipo) => {
    const key = companyKey(ipo); const minimum = investment(ipo); const percent = ipo.gmp?.percent;
    return `<tr>
      <td class="save-cell"><button class="star ${state.saved.has(key) ? "saved" : ""}" data-save="${esc(key)}" aria-label="Save ${esc(ipo.companyName)}">★</button></td>
      <td data-label="Company"><button class="company-button" data-company="${esc(key)}">${esc(ipo.companyName)}</button><span class="subtext">${esc(ipo.platform || "Platform pending")}</span></td>
      <td data-label="Status"><span class="pill ${esc(ipo.status)}">${esc(ipo.status || "pending")}</span></td><td data-label="Exchange">${esc(ipo.exchanges?.join(" + ") || "—")}</td>
      <td data-label="Dates" class="numeric">${esc(date(ipo.openDate))} → ${esc(date(ipo.closeDate))}<span class="subtext">Lists ${esc(date(ipo.listingDate))}</span></td>
      <td data-label="Price / lot" class="numeric">${esc(band(ipo.priceBand))}<span class="subtext">${esc(valueOrDash(ipo.lotSize))} shares / lot</span></td>
      <td data-label="Minimum bid" class="numeric">${minimum == null ? "—" : esc(money.format(minimum))}</td>
      <td data-label="GMP" class="numeric ${percent == null ? "" : percent >= 0 ? "positive" : "negative"}">${esc(gmpText(ipo.gmp))}<span class="subtext">${esc(valueOrDash(ipo.gmpUpdatedOn))}</span></td>
      <td data-label="Subscription" class="numeric">${esc(subscriptionText(ipo))}<span class="subtext">${ipo.subscription ? "NSE consolidated" : "Not available"}</span></td>
      <td data-label="Compare" class="compare-cell"><input class="compare-check" data-compare="${esc(key)}" type="checkbox" aria-label="Compare ${esc(ipo.companyName)}" ${state.compared.has(key) ? "checked" : ""}></td>
    </tr>`;
  }).join("") : `<tr class="empty-row"><td colspan="10">No issues match these filters</td></tr>`;
}

function renderEarly() {
  const query = state.earlyQuery.toLowerCase().trim();
  const rows = state.earlyGmp.filter((row) => !query || row.companyName?.toLowerCase().includes(query));
  $("#early-body").innerHTML = rows.length ? rows.map((row) => { const url = safeUrl(row.detailUrl); const percent = row.gmp?.percent; return `<tr><td data-label="Company"><strong>${esc(valueOrDash(row.companyName))}</strong></td><td data-label="Status"><span class="pill ${esc(row.status)}">${esc(valueOrDash(row.status))}</span><span class="subtext">${esc(valueOrDash(row.category))}</span></td><td data-label="Dates" class="numeric">${esc(date(row.openDate))} → ${esc(date(row.closeDate))}<span class="subtext">Lists ${esc(date(row.listingDate))}</span></td><td data-label="Price / lot">${esc(valueOrDash(row.price))}<span class="subtext">Lot ${esc(valueOrDash(row.lotSize))}</span></td><td data-label="Issue size">${esc(valueOrDash(row.issueSize))}</td><td data-label="GMP" class="${percent == null ? "" : percent >= 0 ? "positive" : "negative"}">${esc(gmpText(row.gmp))}</td><td data-label="Updated">${esc(valueOrDash(row.updatedOn))}</td><td data-label="Source">${url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">Open ↗</a>` : "—"}</td></tr>`; }).join("") : `<tr class="empty-row"><td colspan="8">No early GMP records match</td></tr>`;
}

function renderSources() {
  const labels = { nse: "NSE", bse: "BSE", investorGain: "InvestorGain" };
  $("#source-list").innerHTML = Object.entries(state.sources).map(([key, source]) => `<div class="source-row ${source.ok ? "" : "bad"}"><div><strong><i></i>${esc(labels[key] || key)} · ${source.ok ? "Operational" : "Degraded"}</strong><p>${esc(source.error || "Provider returned normally")}</p></div><span>${esc(source.recordCount ?? 0)} records</span></div>`).join("");
  const rows = [["Delivery", state.meta.delivery], ["Dataset generated", dateTime(state.generatedAt)], ["Response served", dateTime(state.meta.servedAt)], ["Refresh interval", `${state.meta.cacheTtlSeconds ?? 0} seconds`], ["Refresh active", state.meta.refreshInProgress ? "Yes" : "No"], ["API endpoint", API_URL]];
  $("#response-meta").innerHTML = rows.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(valueOrDash(value))}</dd></div>`).join("");
}

function categoryLabel(value) {
  const category = String(value || "Category");
  if (/qualified institutional/i.test(category)) return "QIB";
  if (/retail individual/i.test(category)) return "Retail";
  if (/non institutional investors$/i.test(category.trim())) return "NII";
  if (/employee/i.test(category)) return "Employee";
  if (/shareholder/i.test(category)) return "Shareholder";
  return category.replaceAll(/\s+/g, " ").trim();
}
function hasBidValue(row) { return row.times != null || row.sharesOffered != null || row.sharesBid != null; }
function subscriptionCards(rows = []) {
  const dataRows = rows.filter(hasBidValue);
  if (!dataRows.length) return `<div class="subscription-empty"><strong>Awaiting bid figures</strong><span>NSE has returned the category structure, but no numeric values yet.</span></div>`;
  return `<div class="subscription-cards">${dataRows.map((row) => `<article><div><span>${esc(categoryLabel(row.category))}</span><strong>${row.times == null ? "—" : `${esc(numberFormat.format(row.times))}x`}</strong></div><small>Offered ${esc(row.sharesOffered == null ? "—" : numberFormat.format(row.sharesOffered))} · Bid ${esc(row.sharesBid == null ? "—" : numberFormat.format(row.sharesBid))}</small></article>`).join("")}</div>`;
}

function showDetail(ipo) {
  state.currentDetail = ipo;
  const minimum = investment(ipo);
  const estimate = ipo.priceBand?.max != null && ipo.gmp?.value != null ? ipo.priceBand.max + ipo.gmp.value : null;
  const sourceUrl = safeUrl(ipo.detailUrl);
  const detailFields = [["Open", date(ipo.openDate, true)], ["Close", date(ipo.closeDate, true)], ["Listing", date(ipo.listingDate, true)], ["Lot size", ipo.lotSize ? `${ipo.lotSize} shares` : null], ["Face value", ipo.faceValue == null ? null : money.format(ipo.faceValue)], ["Issue size", ipo.issueSize], ["Estimated listing", estimate == null ? null : money.format(estimate)], ["GMP updated", ipo.gmpUpdatedOn]];
  const keyMetrics = [["Price band", band(ipo.priceBand), ""], ["Minimum bid", minimum == null ? "—" : money.format(minimum), ipo.lotSize ? `1 lot · ${ipo.lotSize} shares` : "1 lot"], ["GMP", gmpText(ipo.gmp), ipo.gmpUpdatedOn ? `Updated ${ipo.gmpUpdatedOn}` : "No current quote"], ["Subscription", subscriptionText(ipo), ipo.subscription?.updatedAt ? `Updated ${ipo.subscription.updatedAt}` : "No current bids"]];
  const canApply = ipo.status !== "closed";
  const bidHelper = canApply && minimum != null ? `<section class="application-helper"><div><span>Application calculator</span><small>At the upper price band</small></div><label><span>Lots</span><input id="bid-lots" type="number" min="1" max="100" value="1" inputmode="numeric"></label><div><span>Shares</span><strong id="bid-shares">${esc(number(ipo.lotSize))}</strong></div><div><span>Amount blocked</span><strong id="bid-amount">${esc(money.format(minimum))}</strong></div></section>` : "";
  const subscriptionSection = ipo.subscription ? `<section class="subscription-section"><div class="section-title"><div><h3>Subscription</h3><p>Official NSE consolidated bid figures by investor category.</p></div><strong>${esc(subscriptionText(ipo))}</strong></div>${subscriptionCards(ipo.subscription.consolidatedBidDetails)}<details class="raw-bids"><summary>View detailed NSE bid rows <span>(${ipo.subscription.nseBidDetails?.filter(hasBidValue).length || 0})</span></summary>${subscriptionCards(ipo.subscription.nseBidDetails)}</details></section>` : `<section class="subscription-section"><div class="subscription-empty"><strong>Subscription unavailable</strong><span>NSE has not published bid figures for this issue.</span></div></section>`;
  $("#detail-content").innerHTML = `<header class="dialog-header"><div><div class="dialog-tags"><span class="pill ${esc(ipo.status)}">${esc(ipo.status || "pending")}</span><span>${esc(ipo.platform || "Platform pending")}</span><span>${esc(ipo.exchanges?.join(" + ") || "Exchange pending")}</span></div><h2>${esc(ipo.companyName)}</h2></div></header><div class="key-metrics">${keyMetrics.map(([label, value, note]) => `<div><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`).join("")}</div><section class="issue-facts"><h3>Issue details</h3><div>${detailFields.map(([label, value]) => `<dl><dt>${esc(label)}</dt><dd>${esc(valueOrDash(value))}</dd></dl>`).join("")}</div></section>${bidHelper}${subscriptionSection}<footer class="dialog-foot"><span>Estimated listing is upper price band + current GMP; it is not a forecast.</span>${sourceUrl ? `<a href="${esc(sourceUrl)}" target="_blank" rel="noreferrer">View GMP source ↗</a>` : ""}</footer>`;
  const dialog = $("#detail-dialog");
  dialog.showModal();
  requestAnimationFrame(() => dialog.scrollTo(0, 0));
}

function renderCompareTray() {
  const selected = state.ipos.filter((ipo) => state.compared.has(companyKey(ipo)));
  $("#compare-tray").hidden = !selected.length; $("#compare-count").textContent = selected.length;
  $("#compare-names").innerHTML = selected.map((ipo) => `<span>${esc(ipo.companyName)}</span>`).join(""); $("#open-compare").disabled = selected.length < 2;
}
function showComparison() {
  const selected = state.ipos.filter((ipo) => state.compared.has(companyKey(ipo)));
  const fields = [["Status", (item) => item.status], ["Platform", (item) => item.platform], ["Exchange", (item) => item.exchanges?.join(" + ")], ["Bid dates", (item) => `${date(item.openDate)} – ${date(item.closeDate)}`], ["Listing", (item) => date(item.listingDate)], ["Price band", (item) => band(item.priceBand)], ["Lot size", (item) => item.lotSize], ["Minimum bid", (item) => investment(item) == null ? null : money.format(investment(item))], ["Face value", (item) => item.faceValue == null ? null : money.format(item.faceValue)], ["Issue size", (item) => item.issueSize], ["GMP", (item) => gmpText(item.gmp)], ["Consolidated subscription", subscriptionText], ["GMP updated", (item) => item.gmpUpdatedOn]];
  $("#compare-content").innerHTML = `<div class="dialog-header"><div><h2>IPO comparison</h2><p>Side-by-side normalized data</p></div></div><div class="table-wrap"><table class="compare-table"><thead><tr><th>Metric</th>${selected.map((item) => `<th>${esc(item.companyName)}</th>`).join("")}</tr></thead><tbody>${fields.map(([label, get]) => `<tr><td>${esc(label)}</td>${selected.map((item) => `<td>${esc(valueOrDash(get(item)))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const dialog = $("#compare-dialog");
  dialog.showModal();
  requestAnimationFrame(() => dialog.scrollTo(0, 0));
}
function renderAll() { $("#issues-count").textContent = state.ipos.length; $("#early-count").textContent = state.earlyGmp.length; renderStats(); renderSchedule(); renderSignals(); renderIssues(); renderEarly(); renderSources(); renderCompareTray(); document.body.classList.remove("is-loading"); document.querySelector("main").setAttribute("aria-busy", "false"); }

async function loadData(refresh = false) {
  if (state.loading) return;
  state.loading = true; if (!state.loaded) renderSkeletons();
  const button = $("#refresh"); const sync = $("#sync-state");
  button.disabled = true; button.classList.add("loading"); button.textContent = refresh ? "Refreshing…" : "Loading…"; sync.className = "sync-state"; sync.innerHTML = "<i></i> Synchronizing"; $("#error-banner").hidden = true;
  try {
    const response = await fetch(refresh ? "/api/refresh" : API_URL, { method: refresh ? "POST" : "GET", cache: "no-store", headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error(`API returned ${response.status}`);
    const data = await response.json(); if (!Array.isArray(data.ipos) || !Array.isArray(data.earlyGmp)) throw new Error("API returned an invalid market payload");
    Object.assign(state, { ipos: data.ipos, earlyGmp: data.earlyGmp, sources: data.sources || {}, overview: data.overview || {}, meta: data.meta || {}, generatedAt: data.generatedAt, loaded: true }); state.lastLoadedAt = Date.now();
    const deliveryLabel = data.meta?.refreshInProgress ? "Refresh in progress" : data.meta?.delivery === "stale" ? "Stored data" : data.meta?.delivery === "database" ? "Database current" : "Live update";
    sync.className = `sync-state ${data.meta?.delivery === "stale" ? "" : "ok"}`; sync.innerHTML = `<i></i> ${deliveryLabel}`; $("#updated-at").textContent = `Generated ${dateTime(data.generatedAt)}`; renderAll();
  } catch (error) {
    sync.className = "sync-state error"; sync.innerHTML = "<i></i> API unavailable"; $("#error-banner").hidden = false; $("#error-banner").textContent = `${error.message}. Verify the backend and DATABASE_URL configuration.`; if (!state.loaded) { document.body.classList.remove("is-loading"); document.querySelector("main").setAttribute("aria-busy", "false"); }
  } finally { state.loading = false; button.disabled = false; button.classList.remove("loading"); button.textContent = "Refresh sources"; }
}

document.addEventListener("click", (event) => {
  const tab = event.target.closest("[data-view]"); if (tab) { document.querySelectorAll("[data-view]").forEach((button) => button.classList.toggle("active", button === tab)); document.querySelectorAll("[data-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.panel === tab.dataset.view)); }
  const company = event.target.closest("[data-company]")?.dataset.company; if (company) { const ipo = state.ipos.find((item) => companyKey(item) === company); if (ipo) showDetail(ipo); }
  const saved = event.target.closest("[data-save]")?.dataset.save; if (saved) { state.saved.has(saved) ? state.saved.delete(saved) : state.saved.add(saved); localStorage.setItem("ipo-saved", JSON.stringify([...state.saved])); renderIssues(); }
  const sort = event.target.closest("[data-sort]")?.dataset.sort; if (sort) { state.direction = state.sort === sort ? state.direction * -1 : 1; state.sort = sort; renderIssues(); }
  const closer = event.target.closest("[data-close]"); if (closer) document.getElementById(closer.dataset.close).close();
});
document.addEventListener("input", (event) => { if (event.target.id !== "bid-lots" || !state.currentDetail) return; const lots = Math.max(1, Math.min(100, Number(event.target.value) || 1)); const lotSize = number(state.currentDetail.lotSize) || 0; const price = state.currentDetail.priceBand?.max || 0; $("#bid-shares").textContent = numberFormat.format(lots * lotSize); $("#bid-amount").textContent = money.format(lots * lotSize * price); });
$("#issues-body").addEventListener("change", (event) => { const key = event.target.dataset.compare; if (!key) return; if (event.target.checked && state.compared.size >= 3) { event.target.checked = false; return; } event.target.checked ? state.compared.add(key) : state.compared.delete(key); renderCompareTray(); });
$("#search").addEventListener("input", (event) => { state.query = event.target.value; renderIssues(); });
$("#early-search").addEventListener("input", (event) => { state.earlyQuery = event.target.value; renderEarly(); });
$("#status-filter").addEventListener("change", (event) => { state.status = event.target.value; renderIssues(); });
$("#platform-filter").addEventListener("change", (event) => { state.platform = event.target.value; renderIssues(); });
$("#saved-filter").addEventListener("change", (event) => { state.savedOnly = event.target.checked; renderIssues(); });
$("#refresh").addEventListener("click", () => loadData(true));
$("#clear-compare").addEventListener("click", () => { state.compared.clear(); renderIssues(); renderCompareTray(); });
$("#open-compare").addEventListener("click", showComparison);
$("#export-csv").addEventListener("click", () => { const headers = ["Company", "Status", "Platform", "Exchanges", "Open", "Close", "Listing", "Price min", "Price max", "Lot", "Minimum bid", "Face value", "Issue size", "GMP", "GMP percent", "Consolidated subscription", "Subscription updated", "GMP updated", "Detail URL"]; const values = filteredIpos().map((item) => [item.companyName, item.status, item.platform, item.exchanges?.join(" + "), item.openDate, item.closeDate, item.listingDate, item.priceBand?.min, item.priceBand?.max, item.lotSize, investment(item), item.faceValue, item.issueSize, item.gmp?.value, item.gmp?.percent, subscriptionTimes(item), item.subscription?.updatedAt, item.gmpUpdatedOn, item.detailUrl]); const csv = [headers, ...values].map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\n"); const link = document.createElement("a"); link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); link.download = "ipo-market.csv"; link.click(); URL.revokeObjectURL(link.href); });
document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); }));
loadData();
setInterval(() => loadData(false), AUTO_REFRESH_MS);
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && Date.now() - state.lastLoadedAt >= AUTO_REFRESH_MS) loadData(false); });
