const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const DAY_LABELS = {
  monday: "Mon",
  tuesday: "Tue",
  wednesday: "Wed",
  thursday: "Thu",
  friday: "Fri",
  saturday: "Sat",
  sunday: "Sun",
};

const state = {
  payload: null,
  restaurants: null,
  project: null,
  query: "",
  restaurant: "",
  cities: new Set(),
  day: "today",
  category: "",
  kind: "",
  status: "active",
  userLocation: null,
  locationMessage: "",
};

const dealsEl = document.querySelector("#deals");
const statsEl = document.querySelector("#stats");
const metaEl = document.querySelector("#meta");
const sourcesEl = document.querySelector("#sources");
const searchEl = document.querySelector("#search");
const restaurantEl = document.querySelector("#restaurant");
const cityPickerEl = document.querySelector("#city-picker");
const citySummaryEl = document.querySelector("#city-summary");
const cityOptionsEl = document.querySelector("#city-options");
const dayEl = document.querySelector("#day");
const categoryEl = document.querySelector("#category");
const kindEl = document.querySelector("#kind");
const statusEl = document.querySelector("#status");
const locateEl = document.querySelector("#locate");
const filtersEl = document.querySelector("#filters");
const filterToggleEl = document.querySelector("#filter-toggle");
const filterCountEl = document.querySelector("#filter-count");
const filterSummaryEl = document.querySelector("#filter-summary");
const themeToggleEl = document.querySelector("#theme-toggle");
const coverageSummaryEl = document.querySelector("#coverage-summary");
const coverageCitiesEl = document.querySelector("#coverage-cities");
const coverageMetricsEl = document.querySelector("#coverage-metrics");
const costNoteEl = document.querySelector("#cost-note");
const roadmapListEl = document.querySelector("#roadmap-list");

dayEl.value = "today";

function todayKey() {
  return DAYS[new Date().getDay() === 0 ? 6 : new Date().getDay() - 1];
}

function selectedDay() {
  return state.day === "today" ? todayKey() : state.day;
}

function renderFilterSummary() {
  const labels = [];
  labels.push(state.day === "today" ? "Today" : state.day ? DAY_LABELS[state.day] : "Any day");
  const cityLabel = state.cities.size === 1 ? [...state.cities][0] : state.cities.size ? `${state.cities.size} cities` : "";
  labels.push(state.restaurant || cityLabel || "All restaurants");
  if (state.category) labels.push(categoryEl.options[categoryEl.selectedIndex]?.text || state.category);
  if (state.kind) labels.push(kindEl.options[kindEl.selectedIndex]?.text || state.kind);

  const activeCount = [
    state.query,
    state.restaurant,
    state.cities.size ? "cities" : "",
    state.day !== "today" ? state.day || "any" : "",
    state.category,
    state.kind,
    state.status !== "active" ? state.status || "all" : "",
    state.userLocation ? "location" : "",
  ].filter(Boolean).length;

  filterSummaryEl.textContent = labels.join(" · ");
  filterCountEl.textContent = activeCount;
  filterCountEl.hidden = activeCount === 0;
}

function formatDate(value) {
  if (!value) return "never";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function normalizeScheduleText(value = "") {
  let text = String(value);
  for (const [day, label] of Object.entries(DAY_LABELS)) {
    text = text.replace(new RegExp(`\\b${day}\\b`, "gi"), label);
  }
  text = text
    .replace(/\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b/gi, (_, hour, minute, period) => {
      const minutes = minute && minute !== "00" ? `:${minute}` : "";
      return `${Number(hour)}${minutes}${period.toLowerCase()}m`;
    })
    .replace(/(\d(?:am|pm))\s+(?:to|[-–—])\s+(?=\d)/gi, "$1-")
    .replace(/(\d:\d{2}(?:am|pm))\s+(?:to|[-–—])\s+(?=\d)/gi, "$1-")
    .replace(/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*[-–—]\s*(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b/g, "$1-$2")
    .replace(/\s+([,;])/g, "$1")
    .replace(/\s{2,}/g, " ")
    .trim();
  return text;
}

function scheduleSignals(value = "") {
  const normalized = normalizeScheduleText(value).toLowerCase();
  return new Set([
    ...(normalized.match(/\b(?:mon|tue|wed|thu|fri|sat|sun)\b/g) || []),
    ...(normalized.match(/\b\d{1,2}(?::\d{2})?(?:am|pm)\b/g) || []),
    ...(normalized.match(/\b(?:all day|every day|daily)\b/g) || []),
  ]);
}

function isValidityRedundant(deal, visibleText) {
  const validity = normalizeScheduleText(deal.validity || "");
  if (!validity || /^check source$/i.test(validity)) return true;
  const signals = scheduleSignals(validity);
  if (!signals.size) return false;
  const visibleSignals = scheduleSignals(visibleText);
  return [...signals].every((signal) => visibleSignals.has(signal));
}

function tagLabel(tag) {
  return tag
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function categoryLabel(categories = []) {
  if (categories.includes("food") && categories.includes("drink")) return "Food + drink";
  if (categories.includes("food")) return "Food";
  if (categories.includes("drink")) return "Drink";
  return "General";
}

function restaurantLabel(name, city) {
  const suffix = ` - ${city}`;
  return city && name.endsWith(suffix) ? name.slice(0, -suffix.length) : name;
}

function locationKeyForDeal(deal) {
  const location = deal.location || {};
  return [deal.restaurant, location.address || deal.city].join("|");
}

function locationSlug(group) {
  return group.key
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function dealText(deal) {
  return [
    deal.restaurant,
    deal.city,
    deal.summary,
    deal.candidate_text,
    deal.validity,
    deal.location?.address,
    ...(deal.details || []),
    ...(deal.tags || []),
    ...(deal.categories || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function matchesDay(deal) {
  const day = selectedDay();
  if (!day) return true;
  const days = deal.applies_days || [];
  return !days.length || days.includes(day) || DAYS.every((item) => days.includes(item));
}

function matchesFilters(deal) {
  const categories = deal.categories || ["general"];
  const isHappyHour = (deal.tags || []).includes("happy_hour") || /happy\s*hour/i.test(dealText(deal));
  return (
    (!state.query || dealText(deal).includes(state.query.toLowerCase())) &&
    (!state.restaurant || deal.restaurant === state.restaurant) &&
    (!state.cities.size || state.cities.has(deal.city)) &&
    (!state.status || deal.status === state.status) &&
    (!state.category || categories.includes(state.category)) &&
    (!state.kind || (state.kind === "happy_hour" ? isHappyHour : !isHappyHour)) &&
    matchesDay(deal)
  );
}

function sourceMap() {
  const map = new Map();
  for (const source of state.payload.sources || []) {
    map.set(source.url, source);
  }
  return map;
}

function groupDeals(deals) {
  const sources = sourceMap();
  const groups = new Map();
  for (const deal of deals) {
    const source = sources.get(deal.source_url) || {};
    const location = deal.location || source.location || {};
    const key = locationKeyForDeal({ ...deal, location });
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        restaurant: deal.restaurant,
        city: deal.city,
        location,
        urls: new Set(),
        deals: [],
      });
    }
    const group = groups.get(key);
    group.urls.add(deal.source_url);
    group.deals.push(deal);
  }

  return [...groups.values()].sort((a, b) => {
    const distanceA = distanceToGroup(a);
    const distanceB = distanceToGroup(b);
    if (state.userLocation && Number.isFinite(distanceA) && Number.isFinite(distanceB)) {
      return distanceA - distanceB || a.restaurant.localeCompare(b.restaurant);
    }
    return a.restaurant.localeCompare(b.restaurant) || a.city.localeCompare(b.city);
  });
}

function renderSelectOptions(select, values, firstLabel) {
  select.innerHTML = `<option value="">${firstLabel}</option>`;
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
}

function updateCitySummary() {
  citySummaryEl.textContent = state.cities.size === 0
    ? "All cities"
    : state.cities.size === 1
      ? [...state.cities][0]
      : `${state.cities.size} cities`;
}

function renderCityOptions(values) {
  cityOptionsEl.innerHTML = "";
  for (const city of values) {
    const label = document.createElement("label");
    label.className = "city-option";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = city;
    input.checked = state.cities.has(city);
    label.append(input, document.createTextNode(city));
    cityOptionsEl.append(label);
  }
  const clear = document.createElement("button");
  clear.className = "city-clear";
  clear.type = "button";
  clear.textContent = "All cities";
  cityOptionsEl.append(clear);
  updateCitySummary();
}

function renderFilterOptions() {
  const cities = new Set(state.payload.scope?.cities || []);
  const restaurants = new Set();
  for (const source of state.payload.sources || []) {
    if (source.city) cities.add(source.city);
    if (source.name) restaurants.add(source.name);
  }
  for (const deal of state.payload.deals || []) {
    if (deal.city) cities.add(deal.city);
    if (deal.restaurant) restaurants.add(deal.restaurant);
  }
  renderCityOptions([...cities].sort());
  renderSelectOptions(restaurantEl, [...restaurants].sort(), "All restaurants");
}

function renderSummary(visibleDeals) {
  const { summary, generated_at: generatedAt, scope } = state.payload;
  const visibleGroups = groupDeals(visibleDeals);
  statsEl.innerHTML = `
    <span><strong>${visibleGroups.length}</strong> restaurants</span>
    <span><strong>${visibleDeals.length}</strong> deals</span>
  `;

  const locationText = state.locationMessage ? ` ${state.locationMessage}` : "";
  const dayText = state.day === "today" ? DAY_LABELS[todayKey()] : state.day ? tagLabel(state.day) : "any day";
  const ageHours = generatedAt ? (Date.now() - new Date(generatedAt).getTime()) / 3600000 : Number.POSITIVE_INFINITY;
  const delayed = ageHours > 36;
  metaEl.innerHTML = `
    <p><strong>${dayText}</strong> deals · Updated ${formatDate(generatedAt)}.${locationText}</p>
    ${delayed ? '<p class="feed-warning"><strong>Refresh delayed.</strong> Deals may be out of date while the automated update recovers.</p>' : ""}
  `;
}

function badge(text, className = "") {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  return span;
}

const ICONS = {
  directions: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22s7-6.1 7-13a7 7 0 1 0-14 0c0 6.9 7 13 7 13Z"></path><circle cx="12" cy="9" r="2.3"></circle></svg>',
  phone: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.4 19.4 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.8a2 2 0 0 1-.4 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z"></path></svg>',
  source: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7"></path><path d="M10 14 21 3"></path><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"></path></svg>',
  chevron: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 18 6-6-6-6"></path></svg>',
};

function actionLink(href, label, iconName, external = false) {
  const link = document.createElement("a");
  link.className = "icon-action";
  link.href = href;
  link.title = label;
  link.setAttribute("aria-label", label);
  link.innerHTML = ICONS[iconName];
  if (external) {
    link.target = "_blank";
    link.rel = "noopener";
  }
  link.addEventListener("click", (event) => event.stopPropagation());
  return link;
}

function mapsUrl(name, address, googleMapsUrl) {
  if (googleMapsUrl) return googleMapsUrl;
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${name} ${address}`)}`;
}

function telUrl(phone) {
  return `tel:${phone.replace(/[^0-9+]/g, "")}`;
}

function distanceMiles(a, b) {
  const radius = 3958.8;
  const toRad = (value) => (value * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLon = toRad(b.longitude - a.longitude);
  const lat1 = toRad(a.latitude);
  const lat2 = toRad(b.latitude);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
  return 2 * radius * Math.asin(Math.sqrt(h));
}

function distanceToGroup(group) {
  if (!state.userLocation || !group.location?.latitude || !group.location?.longitude) return Number.POSITIVE_INFINITY;
  return distanceMiles(state.userLocation, group.location);
}

function distanceLabel(group) {
  const distance = distanceToGroup(group);
  if (!Number.isFinite(distance)) return null;
  return `${distance.toFixed(distance < 10 ? 1 : 0)} mi`;
}

function minutesSinceWeekStart(date) {
  const jsDay = date.getDay();
  const dayIndex = jsDay === 0 ? 6 : jsDay - 1;
  return dayIndex * 1440 + date.getHours() * 60 + date.getMinutes();
}

function parseClock(value) {
  const [hour, minute] = value.split(":").map(Number);
  return hour * 60 + minute;
}

function openStatus(location) {
  const hours = location?.hours;
  if (!hours) return "Hours unknown";
  const now = new Date();
  const current = minutesSinceWeekStart(now);
  const today = DAYS[now.getDay() === 0 ? 6 : now.getDay() - 1];
  const ranges = [];

  DAYS.forEach((day, index) => {
    for (const range of hours[day] || []) {
      const start = index * 1440 + parseClock(range.open);
      let end = index * 1440 + parseClock(range.close);
      if (end <= start) end += 1440;
      ranges.push({ start, end, range, day });
    }
  });

  for (const item of ranges) {
    if (current >= item.start && current < item.end) return `Open until ${formatClock(item.range.close)}`;
    if (current + 1440 >= item.start && current + 1440 < item.end) return `Open until ${formatClock(item.range.close)}`;
  }

  const todayRanges = hours[today] || [];
  if (todayRanges.length) return `Closed now, opens ${formatClock(todayRanges[0].open)}`;
  return "Closed today";
}

function formatClock(value) {
  const [hour, minute] = value.split(":").map(Number);
  const period = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 || 12;
  return `${displayHour}${minute ? `:${String(minute).padStart(2, "0")}` : ""}${period.toLowerCase()}`;
}

function bestDeals(group) {
  return group.deals
    .slice()
    .sort((a, b) => scoreDeal(b) - scoreDeal(a) || (a.summary || "").localeCompare(b.summary || ""))
    .slice(0, 2);
}

function scoreDeal(deal) {
  const tags = deal.tags || [];
  let score = 0;
  if (tags.includes("happy_hour")) score += 4;
  if (tags.includes("percent_off") || tags.includes("bogo") || tags.includes("free")) score += 3;
  if ((deal.applies_days || []).length) score += 2;
  if (deal.time_window) score += 1;
  return score;
}

function renderDealRow(deal) {
  const row = document.createElement("article");
  row.className = "deal-row";

  const main = document.createElement("div");
  main.className = "deal-main";

  const title = document.createElement("h3");
  title.textContent = normalizeScheduleText(deal.summary || deal.candidate_text);
  main.append(title);

  const detailItems = (deal.details || []).filter((item) => item && item !== title.textContent).slice(0, 3);
  if (detailItems.length) {
    const details = document.createElement("p");
    details.className = "deal-details";
    details.textContent = normalizeScheduleText(detailItems.join(" · "));
    main.append(details);
  }

  const meta = document.createElement("div");
  meta.className = "deal-meta";
  const visibleText = [title.textContent, ...detailItems].join(" ");
  if (!isValidityRedundant(deal, visibleText)) {
    meta.append(badge(normalizeScheduleText(deal.validity), "validity"));
  }
  meta.append(badge(categoryLabel(deal.categories), "category"));
  const visibleTags = new Set(["happy_hour", "bogo", "percent_off", "free"]);
  const displayTags = (deal.tags || []).filter((tag) => visibleTags.has(tag)).slice(0, 1);
  for (const tag of displayTags) meta.append(badge(tagLabel(tag)));
  main.append(meta);

  if (deal.status === "stale") {
    const stale = document.createElement("p");
    stale.className = "stale-note";
    stale.textContent = `Not found in the latest check · Last seen ${formatDate(deal.last_seen)}`;
    main.append(stale);
  }

  row.append(main);
  return row;
}

function locationQualifier(address = "") {
  const street = address.split(",")[0].replace(/^\d+\s+/, "").replace(/\s+(?:Ste|Suite|Unit|#)\s*\S+.*$/i, "").trim();
  if (/^(?:CA-1|Pacific Coast (?:Hwy|Highway))$/i.test(street)) return "PCH";
  return street;
}

function renderGroup(group, needsQualifier = false) {
  const section = document.createElement("details");
  section.className = "location";
  section.id = locationSlug(group);
  section.open = Boolean(state.restaurant || state.query);

  const summary = document.createElement("summary");
  summary.className = "location-heading";

  const titleWrap = document.createElement("div");
  titleWrap.className = "location-title";
  const title = document.createElement("h2");
  const baseLabel = restaurantLabel(group.restaurant, group.city);
  const qualifier = needsQualifier ? locationQualifier(group.location?.address) : "";
  title.textContent = qualifier ? `${baseLabel} · ${qualifier}` : baseLabel;
  const sub = document.createElement("p");
  const bits = [group.city, distanceLabel(group), openStatus(group.location)].filter(Boolean);
  sub.textContent = bits.join(" · ");
  titleWrap.append(title, sub);

  const preview = document.createElement("div");
  preview.className = "deal-preview";
  for (const deal of bestDeals(group)) preview.append(badge(normalizeScheduleText(deal.summary || "Deal")));

  const actions = document.createElement("div");
  actions.className = "location-actions";
  actions.append(badge(`${group.deals.length} ${group.deals.length === 1 ? "deal" : "deals"}`, "deal-count"));
  if (group.location?.address) {
    actions.append(actionLink(mapsUrl(group.restaurant, group.location.address, group.location.google_maps_url), "Directions", "directions", true));
  }
  if (group.location?.phone) {
    actions.append(actionLink(telUrl(group.location.phone), `Call ${group.location.phone}`, "phone"));
  }
  for (const [index, url] of [...group.urls].entries()) {
    const label = group.urls.size > 1 ? `Official source ${index + 1}` : "Official source";
    actions.append(actionLink(url, label, "source", true));
  }

  const disclosure = document.createElement("span");
  disclosure.className = "disclosure";
  disclosure.innerHTML = ICONS.chevron;

  summary.append(titleWrap, preview, actions, disclosure);
  section.append(summary);

  const body = document.createElement("div");
  body.className = "location-body";
  const rows = document.createElement("div");
  rows.className = "deal-list";
  for (const deal of group.deals) rows.append(renderDealRow(deal));
  body.append(rows);
  section.append(body);
  return section;
}

function renderDeals() {
  const deals = (state.payload.deals || []).filter(matchesFilters);
  const groups = groupDeals(deals);
  const nameCounts = groups.reduce((counts, group) => counts.set(group.restaurant, (counts.get(group.restaurant) || 0) + 1), new Map());
  dealsEl.innerHTML = "";
  renderSummary(deals);

  if (!groups.length) {
    const selected = (state.restaurants?.restaurants || []).find((item) => item.name === state.restaurant);
    if (selected) {
      const link = selected.website_url
        ? ` <a href="${selected.website_url}" target="_blank" rel="noopener">Check its official site</a>.`
        : "";
      dealsEl.innerHTML = `<p class="empty"><strong>No verified special found for ${selected.name} yet.</strong>${link}</p>`;
    } else {
      dealsEl.innerHTML = '<p class="empty">No matching verified deals found.</p>';
    }
    return;
  }

  for (const group of groups) dealsEl.append(renderGroup(group, nameCounts.get(group.restaurant) > 1));
}

function renderSources() {
  const failed = (state.payload.sources || []).filter((source) => !source.ok && !source.retired);
  if (!failed.length) {
    sourcesEl.innerHTML = "";
    return;
  }
  sourcesEl.innerHTML = `
    <h2>Sources Needing Attention</h2>
    ${failed
      .map(
        (source) => `
          <article>
            <strong>${source.name}</strong>
            <a href="${source.url}" target="_blank" rel="noopener">${source.url}</a>
            <p>${source.error}</p>
          </article>
        `
      )
      .join("")}
  `;
}

function compactNumber(value) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value || 0);
}

function dateOnly(value) {
  if (!value) return "Pending";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(value));
}

function estimatedActivation(statuses, city, queuedCities) {
  const interval = state.project?.queue_activation_days || 7;
  const activeDates = Object.values(statuses)
    .filter((item) => item.status === "active" && item.activated_at)
    .map((item) => new Date(item.activated_at).getTime());
  const latest = Math.max(...activeDates);
  const queueIndex = queuedCities.indexOf(city);
  if (!Number.isFinite(latest) || queueIndex < 0) return null;
  return new Date(latest + (queueIndex + 1) * interval * 86400000);
}

function renderProjectStatus() {
  const coverage = state.restaurants?.coverage || {};
  const statuses = state.restaurants?.area_status || {};
  const activeCities = coverage.cities || [];
  const queuedCities = coverage.queued_cities || [];
  coverageSummaryEl.textContent = `${activeCities.length} live · ${queuedCities.length} queued · next ${dateOnly(state.restaurants?.refresh_after)}`;

  coverageCitiesEl.innerHTML = "";
  for (const city of [...activeCities, ...queuedCities]) {
    const info = statuses[city] || {};
    const active = info.status === "active";
    const row = document.createElement("div");
    row.className = "coverage-row";
    const name = document.createElement("strong");
    name.textContent = city;
    const status = badge(active ? "Live" : "Queued", `coverage-state ${active ? "live" : "queued"}`);
    const note = document.createElement("span");
    note.className = "coverage-date";
    const estimate = estimatedActivation(statuses, city, queuedCities);
    const cityCount = info.restaurant_count ?? (state.restaurants?.restaurants || []).filter((item) => item.city === city).length;
    note.textContent = active
      ? `${compactNumber(cityCount)} spots · scanned ${dateOnly(info.last_refreshed)}`
      : `Est. ${dateOnly(estimate)}`;
    row.append(name, status, note);
    coverageCitiesEl.append(row);
  }

  const metrics = [
    ["Restaurants found", compactNumber(coverage.restaurant_count)],
    ["Official websites", compactNumber(coverage.official_websites)],
    ["Specials pages", compactNumber(coverage.specials_pages_found)],
    ["Gemini batch", `${state.project?.gemini_pages_per_run || 30}/run`],
    ["City activation", `1/${state.project?.queue_activation_days || 7} days`],
    ["City rescan", `${state.project?.area_refresh_days || 35} days`],
  ];
  coverageMetricsEl.innerHTML = metrics
    .map(([label, value]) => `<div><strong>${value}</strong><span>${label}</span></div>`)
    .join("");
  costNoteEl.textContent = state.project?.cost_note || "The pipeline is configured around free-tier limits.";

  roadmapListEl.innerHTML = (state.project?.roadmap || [])
    .map((item) => `
      <article>
        <span class="roadmap-state ${item.status}">${item.status}</span>
        <div><strong>${item.title}</strong><p>${item.detail}</p></div>
      </article>
    `)
    .join("");
}

function rerender() {
  renderDeals();
  renderSources();
}

function requestLocation() {
  if (!navigator.geolocation) {
    state.locationMessage = "Location is not available in this browser.";
    rerender();
    return;
  }
  locateEl.disabled = true;
  locateEl.textContent = "Finding...";
  navigator.geolocation.getCurrentPosition(
    (position) => {
      state.userLocation = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
      };
      state.locationMessage = "Sorted by distance.";
      locateEl.textContent = "Distance on";
      renderFilterSummary();
      rerender();
    },
    () => {
      state.locationMessage = "Location permission was not enabled.";
      locateEl.disabled = false;
      locateEl.textContent = "Use my location";
      rerender();
    },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 }
  );
}

async function init() {
  const [dealsResponse, restaurantsResponse, projectResponse] = await Promise.all([
    fetch("data/deals.json", { cache: "no-store" }),
    fetch("data/restaurants.json", { cache: "no-store" }).catch(() => null),
    fetch("data/project.json", { cache: "no-store" }).catch(() => null),
  ]);
  state.payload = await dealsResponse.json();
  state.restaurants = restaurantsResponse?.ok ? await restaurantsResponse.json() : null;
  state.project = projectResponse?.ok ? await projectResponse.json() : null;
  renderFilterOptions();
  renderProjectStatus();
  renderDeals();
}

searchEl.addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  renderFilterSummary();
  rerender();
});

restaurantEl.addEventListener("change", (event) => {
  state.restaurant = event.target.value;
  renderFilterSummary();
  rerender();
  if (state.restaurant) {
    requestAnimationFrame(() => {
      const group = groupDeals((state.payload.deals || []).filter(matchesFilters))[0];
      const section = group && document.getElementById(locationSlug(group));
      if (section) {
        section.open = true;
        section.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
});

cityOptionsEl.addEventListener("change", (event) => {
  if (!event.target.matches('input[type="checkbox"]')) return;
  if (event.target.checked) state.cities.add(event.target.value);
  else state.cities.delete(event.target.value);
  updateCitySummary();
  renderFilterSummary();
  rerender();
});

cityOptionsEl.addEventListener("click", (event) => {
  if (!event.target.matches(".city-clear")) return;
  state.cities.clear();
  for (const input of cityOptionsEl.querySelectorAll('input[type="checkbox"]')) input.checked = false;
  updateCitySummary();
  renderFilterSummary();
  rerender();
});

document.addEventListener("click", (event) => {
  if (!cityPickerEl.contains(event.target)) cityPickerEl.open = false;
});

dayEl.addEventListener("change", (event) => {
  state.day = event.target.value;
  renderFilterSummary();
  rerender();
});

categoryEl.addEventListener("change", (event) => {
  state.category = event.target.value;
  renderFilterSummary();
  rerender();
});

kindEl.addEventListener("change", (event) => {
  state.kind = event.target.value;
  renderFilterSummary();
  rerender();
});

statusEl.addEventListener("change", (event) => {
  state.status = event.target.value;
  renderFilterSummary();
  rerender();
});

filterToggleEl.addEventListener("click", () => {
  const expanded = filtersEl.classList.toggle("is-open");
  filterToggleEl.setAttribute("aria-expanded", String(expanded));
});

locateEl.addEventListener("click", requestLocation);

function syncThemeButton() {
  const dark = document.documentElement.dataset.theme === "dark";
  const label = dark ? "Use light mode" : "Use dark mode";
  themeToggleEl.setAttribute("aria-label", label);
  themeToggleEl.title = label;
}

themeToggleEl.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("theme", next);
  syncThemeButton();
});

renderFilterSummary();
syncThemeButton();

init().catch((error) => {
  dealsEl.innerHTML = `<p class="empty">Could not load deals: ${error.message}</p>`;
});
