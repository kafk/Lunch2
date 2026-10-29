---
name: source-validation
description: >-
  Independently verify lunch scraping & normalization results against raw page evidence
  and a restaurant TargetSpec before publishing. Flags wrong-content (à la carte/dinner/booking text),
  price anomalies, cadence mismatches, and stale menus.
---

# source-validation

This skill performs deterministic intent and evidence validation on scraped lunch menus.

## Checks
1. **Selection Intent**: Verifies the scraper selected the lunch block, not à la carte, dinner, or booking hours.
2. **Price Sanity**: Verifies dishes fit standard Swedish lunch price range (90–195 SEK).
3. **Cadence & Volume**: Verifies menu matches weekly vs daily expectations.
4. **Freshness**: Checks calendar week against current week.
5. **Dish Evidence**: Confirms dishes actually exist in raw source text within proximity of price/day markers.
