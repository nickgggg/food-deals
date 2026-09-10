# HB + Fountain Valley Food Deals

A lightweight, serverless deals aggregator for local restaurant specials, beginning with Huntington Beach and Fountain Valley.

The project runs entirely on GitHub:

- GitHub Actions runs the crawler every day at 14:37 UTC, plus manual `workflow_dispatch` runs.
- The crawler writes normalized JSON to `docs/data/deals.json`.
- GitHub Pages serves the static frontend from `docs/`.
- Google Places builds a weekly nearby-restaurant inventory and supplies current business details.
- The crawler uses only the Python standard library, so there are no package installs.

## Current Scope

Curated sources live in `crawler/sources.json`. A weekly discovery pass scans the configured map grid, finds official websites and likely specials pages, and writes the restaurant inventory to `docs/data/restaurants.json`. Discovered pages form a review queue; they publish only after a source-specific parser or explicit `publish` approval prevents generic page noise from reaching the site.

The discovery job requires the repository Actions secret `GOOGLE_PLACES_API_KEY`, with Places API (New) enabled. Its map bounds and refresh interval live in `crawler/places_config.json`.

## What It Finds

The candidate detector intentionally stays broad instead of hard-coding exact offers. It tags text matching patterns such as:

- Percent discounts like `20% off`, `1/2 off`, or `% off`
- Dollar amounts like `$5`, `$10 lunch`, `$2 off`, or `2 for $12`
- BOGO and buy-one-get-one phrasing
- Happy hour and late-night specials
- Weekday specials like Taco Tuesday, Wine Wednesday, weekend brunch, daily specials, and all-day offers
- Free item, combo, discount, coupon, promo, special, offer, and rewards language

## Data Shape

Each deal includes:

- `restaurant`
- `city`
- `source_url`
- `candidate_text`
- `tags`
- `first_seen`
- `last_seen`
- `status`
- `is_stale`
- `days_since_seen`

## Staleness Handling

A deal gets a stable ID from its source URL and normalized candidate text. When the same candidate is found again, `first_seen` is preserved and `last_seen` updates.

If a previously seen deal is missing from a later crawl, it stays in the JSON as `status: "stale"` instead of disappearing immediately. Stale deals are retained for up to 90 days, then dropped.

## GitHub Pages

Enable Pages in the repo settings:

1. Go to Settings -> Pages.
2. Set source to `Deploy from a branch`.
3. Choose branch `main` and folder `/docs`.
4. Save.

Once enabled, the frontend will read the latest `docs/data/deals.json` and show active/stale filters, city filtering, search, source links, and failed-source notices.

## Running Manually

From the Actions tab, run the `Update deals` workflow manually whenever you want an immediate refresh.
