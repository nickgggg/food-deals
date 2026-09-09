# HB + Fountain Valley Food Deals

A lightweight, serverless deals aggregator for Huntington Beach and Fountain Valley restaurant specials.

The project runs entirely on GitHub:

- GitHub Actions runs the crawler every day at 14:37 UTC, plus manual `workflow_dispatch` runs.
- The crawler writes normalized JSON to `docs/data/deals.json`.
- GitHub Pages serves the static frontend from `docs/`.
- The crawler uses only the Python standard library, so there are no package installs or paid services.

## Current Scope

The initial source list lives in `crawler/sources.json` and covers Huntington Beach plus a smaller Fountain Valley seed set. To expand, add another object with `name`, `city`, `url`, and optional `notes`.

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
