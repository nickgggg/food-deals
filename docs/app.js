const state = {
  payload: null,
  query: "",
  city: "",
  status: "active",
};

const dealsEl = document.querySelector("#deals");
const statsEl = document.querySelector("#stats");
const metaEl = document.querySelector("#meta");
const sourcesEl = document.querySelector("#sources");
const searchEl = document.querySelector("#search");
const cityEl = document.querySelector("#city");
const statusEl = document.querySelector("#status");
const template = document.querySelector("#deal-template");

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

function matchesFilters(deal) {
  const haystack = [
    deal.restaurant,
    deal.city,
    deal.candidate_text,
    ...(deal.tags || []),
  ]
    .join(" ")
    .toLowerCase();

  return (
    (!state.query || haystack.includes(state.query.toLowerCase())) &&
    (!state.city || deal.city === state.city) &&
    (!state.status || deal.status === state.status)
  );
}

function renderCityOptions() {
  const cities = [...new Set((state.payload.deals || []).map((deal) => deal.city))].sort();
  for (const city of cities) {
    const option = document.createElement("option");
    option.value = city;
    option.textContent = city;
    cityEl.append(option);
  }
}

function renderSummary() {
  const { summary, generated_at: generatedAt, scope } = state.payload;
  statsEl.innerHTML = `
    <span><strong>${summary.active_deals}</strong> active</span>
    <span><strong>${summary.stale_deals}</strong> stale</span>
    <span><strong>${summary.healthy_sources}</strong> sources ok</span>
  `;

  metaEl.innerHTML = `
    <p>Updated ${formatDate(generatedAt)}. Stale means the deal was previously found but has not appeared again in the latest crawl. Old stale items drop after ${scope.drop_after_days} days.</p>
  `;
}

function renderDeals() {
  const deals = (state.payload.deals || []).filter(matchesFilters);
  dealsEl.innerHTML = "";

  if (!deals.length) {
    dealsEl.innerHTML = '<p class="empty">No matching deals found yet.</p>';
    return;
  }

  for (const deal of deals) {
    const node = template.content.cloneNode(true);
    node.querySelector("h2").textContent = deal.restaurant;
    node.querySelector(".city").textContent = deal.city;
    node.querySelector(".candidate").textContent = deal.candidate_text;
    node.querySelector(".status").textContent = deal.status;
    node.querySelector(".status").classList.add(deal.status);
    node.querySelector("a").href = deal.source_url;
    node.querySelector(".seen").textContent =
      deal.status === "stale"
        ? `Last seen ${formatDate(deal.last_seen)}`
        : `First seen ${formatDate(deal.first_seen)}`;

    const tags = node.querySelector(".tags");
    for (const tag of deal.tags || []) {
      const badge = document.createElement("span");
      badge.textContent = tagLabel(tag);
      tags.append(badge);
    }
    dealsEl.append(node);
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
  renderDeals();
});

cityEl.addEventListener("change", (event) => {
  state.city = event.target.value;
  renderDeals();
});

statusEl.addEventListener("change", (event) => {
  state.status = event.target.value;
  renderDeals();
});

init().catch((error) => {
  dealsEl.innerHTML = `<p class="empty">Could not load deals: ${error.message}</p>`;
});
