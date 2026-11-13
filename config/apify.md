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
3. Schedule the saved task for **07:00 UTC, Monday-Friday**
   (`0 7 * * 1-5`, timezone UTC), before Vercel's 07:10 UTC menu refresh.
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
Only Instagram CDN image URLs are accepted, and at most two images are sent
to OCR per refresh. Carousel images are supported.

After deployment, refresh `/api/menus?refresh=true` and inspect Backside:
`source` should be `Apify Instagram image OCR`, `menu_source_url` should point
to the verified post, and `menu_week`/`menu_year` should match today.
Failures appear in `scrape_reasons`; a fallback is not proof of Apify success.
Expired image links require a fresh scheduled task run.
