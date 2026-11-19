# Backside Instagram menus through Apify

The optional Apify path reads the latest **successful run of a saved task**.
Lunchdejt never starts an Actor or a paid run. The existing daily menu cache
still applies. If Apify cannot provide a verified menu, the direct Instagram
scraper and then the current-week saved backup are tried as before.

## Apify

1. Save an `apify/instagram-scraper` task with **Posts**, profile
   `https://www.instagram.com/restaurangbackside/`, and **5 results per URL**.
2. Keep the date filter empty. Set the task's maximum cost per run to **$0.10**
   and timeout to **120 seconds**.
3. Add the saved task to the shared **Monday 09:05 Europe/Stockholm** schedule
   (`5 9 * * 1`). Keep the separate **Tuesday-Friday 07:00 UTC** schedule
   (`0 7 * * 2-5`), before Vercel's unchanged 07:10 UTC refresh on those days.
4. Run the task once to populate its dataset.

At the console price of $2.70/1,000 results, 22 five-result runs are about
$0.30/month, excluding other fees and OCR usage. Review pricing and account
limits in Apify. Schedule only this saved task, not both the task and Actor.

## Vercel

Set these project environment variables for **Production**, then deploy:

| Variable | Value |
| --- | --- |
| `APIFY_API_TOKEN` | Private Apify API token with permission to read the task's dataset |
| `APIFY_BACKSIDE_TASK_ID` | Saved task ID from its console URL, not an Actor ID or run ID |
| `GEMINI_API_KEY` | Existing Gemini OCR key (`GOOGLE_API_KEY` is also supported) |

Enter tokens directly in Vercel's environment settings. Never commit them,
paste them in chat, or include them in URLs. Removing both Apify variables
disables the provider; partial configuration produces an explicit reason.

## Validation and troubleshooting

The response must belong to the requested restaurant. Results are sorted by
publication time rather than dataset order. Posts from the preceding Sunday
are allowed, but OCR must verify the image's current ISO year/week and source.
Old, future-dated, wrong-account, or wrong-week posts are rejected.
If the image's week heading is wrong, a current-week caption and all five
printed weekday dates must independently match the current week instead.
Only Instagram CDN image URLs are accepted, and at most two images are sent
to OCR per refresh. Carousel images are supported.

After deployment, refresh `/api/menus?refresh=true` and inspect Backside:
`source` should be `Apify Instagram image OCR`, `menu_source_url` should point
to the verified post, and `menu_week`/`menu_year` should match today.
Failures appear in `scrape_reasons`; a fallback is not proof of Apify success.
Expired image links require a fresh scheduled task run.

## Kvartersmenyn: Ferraris Kök and Arya

The optional Kvartersmenyn provider reads the latest successful run of a
separate `apify/website-content-crawler` task. It does not start paid runs
from visitor requests. Configure the task with the two restaurant subdomain
URLs, maximum depth 0, maximum 2 pages, Swedish residential proxy, HTML
transformer `None`, and **Save HTML to key-value store**. Limit retries and
session rotations, and set a run timeout and spending limit in Apify.

Set `APIFY_KVARTERSMENYN_TASK_ID` in Vercel alongside the existing
`APIFY_API_TOKEN`. Schedule the task for Mondays at 09:05 Europe/Stockholm,
alongside the Backside task, before the 09:15 Swedish-time Lunchdejt refresh.
Vercel uses Monday 07:15 and 08:15 UTC slots; only the slot matching Sweden's
current UTC offset refreshes the menus. A menu published after the Apify run will not be
retrieved by Apify until another task run; a manual run can update it sooner.
Costs depend on compute, residential proxy traffic and storage.

Lunchdejt matches the exact restaurant URL, retrieves the saved HTML only from
Apify, removes hidden watermark tags, and requires the current ISO week and
year plus five populated weekday sections. If the task fails or its data is
missing or stale, the existing direct, AI and saved-menu fallbacks remain.
