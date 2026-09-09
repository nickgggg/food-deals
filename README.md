# HB + Fountain Valley Food Deals

A lightweight, serverless deals aggregator for Huntington Beach and Fountain Valley restaurants.

The project runs entirely on GitHub:

- A scheduled GitHub Actions workflow runs the crawler.
- The crawler writes normalized JSON to `docs/data/deals.json`.
- GitHub Pages serves the static frontend from `docs/`.

## What It Finds

The crawler looks for broad deal/special language instead of hard-coded offers, including:

- Percent discounts like `20% off` or `% off`
- Dollar amounts like `$5`, `$10 lunch`, or `2 for $12`
- BOGO and buy-one-get-one phrasing
- Happy hour and late-night specials
- Weekday specials like Taco Tuesday or weekend brunch
- Free item, combo, discount, coupon, promo, special, and rewards language

## Data Shape

Each deal includes restaurant name, city, source URL, matched candidate text, tags, first/last seen timestamps, and staleness metadata.

## GitHub Pages

After GitHub Pages is enabled for this repository, set it to serve from the `docs/` folder on the `main` branch.

The scheduled crawler will keep `docs/data/deals.json` fresh without any server or paid infrastructure.