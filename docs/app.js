const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];

const state = {
  payload: null,
  query: "",
  city: "",
  day: "",
  category: "",
  status: "active",
};

const dealsEl = document.querySelector("#deals");
const statsEl = document.querySelector("#stats");
const metaEl = document.querySelector("#meta");
const sourcesEl = document.querySelector("#sources");
const searchEl = document.querySelector("#search");
const cityEl = document.querySelector("#city");
const dayEl = document.querySelector("#day");
const categoryEl = document.querySelector("#category");
const statusEl = document.querySelector("#status");

function formatDate(value) {
  if (!value) return "never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
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

function dealText(deal) {
  return [
    deal.restaurant,
    deal.city,
    deal.summary,
    deal.candidate_text,
    deal.validity,
    ...(deal.details || []),
    ...(deal.tags || []),
    ...(deal.categories || []),
  ]
    .join(" ")
    .toLowerCase();
}

function matchesDay(deal) {
  if (!state.day) return true;
  const days = deal.applies_days || [];
  return days.length === 0 || days.includes(state.day) || DAYS.every((day) => days.includes(day));
}

function matchesFilters(deal) {
  const categories = deal.categories || ["general"];
  return (
    (!state.query || dealText(deal).includes(state.query.toLowerCase())) &&
    (!state.city || deal.city === state.city) &&
    (!state.status || deal.status === state.status) &&
    (!state.category || categories.includes(state.category)) &&
    matchesDay(deal)
  );
}

function groupDeals(deals) {
  const groups = new Map();
  for (const deal of deals) {
    const key = `${deal.city}|${deal.restaurant}|${deal.source_url}`;
    if (!groups.has(key)) {
      groups.set(key, {
        restaurant: deal.restaurant,
        city: deal.city,
        source_url: deal.source_url,
        deals: [],
      });
    }
    groups.get(key).deals.push(deal);
  }
  return [...groups.values()].sort((a, b) => {
    const city = a.city.localeCompare(b.city);
    return city || a.restaurant.localeCompare(b.restaurant);
  });
}

function renderCityOptions() {
  const cities = new Set(state.payload.scope?.cities || []);
  for (const source of state.payload.sources || []) cities.add(source.city);
  for (const deal of state.payload.deals || []) cities.add(deal.city);

  for (const city of [...cities].sort()) {
    const option = document.createElement("option");
    option.value = city;
    option.textContent = city;
    cityEl.append(option);
  }
}

function renderSummary() {
  const { summary, generated_at: generatedAt, scope } = state.payload;
  const groups = groupDeals((state.payload.deals || []).filter((deal) => deal.status === "active"));
  statsEl.innerHTML = `
    <span><strong>${groups.length}</strong> locations</span>
    <span><strong>${summary.active_deals}</strong> active deals</span>
    <span><strong>${summary.healthy_sources}</strong> sources ok</span>
  `;

  metaEl.innerHTML = `
    <p>Updated ${formatDate(generatedAt)}. Day and type filters use best-effort parsing from each source page; source links remain the final check. Old stale items drop after ${scope.drop_after_days} days.</p>
  `;
}

function badge(text, className = "") {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  return span;
}

function renderDealRow(deal) {
  const row = document.createElement("article");
  row.className = "deal-row";

  const main = document.createElement("div");
  main.className = "deal-main";

  const title = document.createElement("h3");
  title.textContent = deal.summary || deal.candidate_text;
  main.append(title);

  const details = (deal.details || []).filter((item) => item !== title.textContent).slice(0, 4);
  if (details.length) {
    const detailList = document.createElement("ul");
    detailList.className = "deal-details";
    for (const item of details) {
      const li = document.createElement("li");
      li.textContent = item;
      detailList.append(li);
    }
    main.append(detailList);
  }

  const meta = document.createElement("div");
  meta.className = "deal-meta";
  meta.append(badge(deal.validity || "Check source for current day/time", "validity"));
  meta.append(badge(categoryLabel(deal.categories), "category"));
  for (const tag of deal.tags || []) meta.append(badge(tagLabel(tag)));
  main.append(meta);

  const side = document.createElement("div");
  side.className = "deal-side";
  side.append(badge(deal.status, `status ${deal.status}`));
  const seen = document.createElement("span");
  seen.className = "seen";
  seen.textContent = deal.status === "stale" ? `Last seen ${formatDate(deal.last_seen)}` : `Seen ${formatDate(deal.last_seen)}`;
  side.append(seen);

  row.append(main, side);
  return row;
}

function renderDeals() {
  const deals = (state.payload.deals || []).filter(matchesFilters);
  const groups = groupDeals(deals);
  dealsEl.innerHTML = "";

  if (!groups.length) {
    dealsEl.innerHTML = '<p class="empty">No matching deals found yet.</p>';
    return;
  }

  for (const group of groups) {
    const section = document.createElement("section");
    section.className = "location";

    const heading = document.createElement("header");
    heading.className = "location-heading";

    const titleWrap = document.createElement("div");
    const title = document.createElement("h2");
    title.textContent = group.restaurant;
    const city = document.createElement("p");
    city.textContent = group.city;
    titleWrap.append(title, city);

    const actions = document.createElement("div");
    actions.className = "location-actions";
    actions.append(badge(`${group.deals.length} deal${group.deals.length === 1 ? "" : "s"}`));
    const source = document.createElement("a");
    source.href = group.source_url;
    source.target = "_blank";
    source.rel = "noopener";
    source.textContent = "Source";
    actions.append(source);

    heading.append(titleWrap, actions);
    section.append(heading);

    const rows = document.createElement("div");
    rows.className = "deal-list";
    for (const deal of group.deals) rows.append(renderDealRow(deal));
    section.append(rows);
    dealsEl.append(section);
  }
}

function renderSources() {
  const failed = (state.payload.sources || []).filter((source) => !source.ok);
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

function rerender() {
  renderDeals();
}

async function init() {
  const response = await fetch("data/deals.json", { cache: "no-store" });
  state.payload = await response.json();
  renderCityOptions();
  renderSummary();
  renderDeals();
  renderSources();
}

searchEl.addEventListener("input", (event) => {
  state.query = event.target.value.trim();
  rerender();
});

cityEl.addEventListener("change", (event) => {
  state.city = event.target.value;
  rerender();
});

dayEl.addEventListener("change", (event) => {
  state.day = event.target.value;
  rerender();
});

categoryEl.addEventListener("change", (event) => {
  state.category = event.target.value;
  rerender();
});

statusEl.addEventListener("change", (event) => {
  state.status = event.target.value;
  rerender();
});

init().catch((error) => {
  dealsEl.innerHTML = `<p class="empty">Could not load deals: ${error.message}</p>`;
});
