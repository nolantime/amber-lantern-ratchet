# Price Tracker

Tracks prices for products you add to `items.yml`, checks them on a schedule
via GitHub Actions, and shows current price / historical low on a small
dashboard hosted with GitHub Pages.

This copy is seeded from a shopping list CSV (`C20 Road Box - Sheet1.csv`) —
`csv_to_items.py` converts it into `items.yml`, one entry per row, grouped
by the CSV's `Category` and sorted by `Priority` on the dashboard. Rows
marked `Purchased` are skipped.

## Setup (one-time, ~5 minutes)

1. **Create a new GitHub repo** and push these files to it (or upload them
   through the GitHub web UI — "Add file" → "Upload files").

2. **Add your items.** Each item in `items.yml` can list several `options` —
   different retailers or brands for the same product — so you can compare
   a recommended house brand against name-brand alternatives:
   ```yaml
   items:
     - name: "3/8\" Drive Ratchet"
       category: "Hand Tools"
       priority: "High"
       qty: 1
       budget: 50
       recommended: "ICON G2 3/8 in. Drive Ratchet"
       options:
         - label: "ICON G2 (Harbor Freight)"
           url: "https://www.harborfreight.com/..."
         - label: "Tekton (Amazon)"
           url: "https://www.amazon.com/..."
           selector: "span.a-price-whole"   # only needed if auto-detection fails
   ```
   The dashboard highlights the cheapest option per item and rolls up
   budgeted vs. tracked totals across all items.

   To regenerate `items.yml` from the CSV (e.g. after editing the sheet),
   run `python csv_to_items.py` — it preserves any `options` you've already
   filled in for items that still exist.

3. **Enable GitHub Pages.**
   Repo → Settings → Pages → under "Build and deployment", set
   **Source: Deploy from a branch**, branch `main`, folder `/docs`. Save.
   Your dashboard will be live at `https://<your-username>.github.io/<repo-name>/`
   within a minute or two.

4. **Enable Actions** if prompted (Settings → Actions → allow workflows to
   run), and make sure workflow permissions allow it to push commits:
   Settings → Actions → General → Workflow permissions →
   **Read and write permissions**.

5. **Run it once manually** to check it works: go to the **Actions** tab →
   "Track prices" → **Run workflow**. After it finishes, refresh your
   dashboard — you should see your items with their first price reading.

After that, it runs automatically every 6 hours (edit the cron schedule in
`.github/workflows/track-prices.yml` if you want it more/less frequent —
GitHub's minimum practical interval is about 5 minutes, but very frequent
scraping is more likely to get you rate-limited or blocked by a site).

## How price detection works

For each option URL, `scrape.py` tries, in order:
1. Your custom `selector` on that option, if you gave one
2. Structured product data (`schema.org`/JSON-LD) embedded in the page —
   works out of the box on a lot of sites
3. Common price meta tags
4. A generic fallback that looks for elements with "price" in their
   class/id

If none of these find a price, the dashboard will show "not found" next to
that option — that's your signal to add a `selector` for it. Items with an
empty `options: []` list are skipped by the scraper and shown dimmed on the
dashboard as still needing links.

## Notes and limitations

- For each option, `scrape.py` tries a plain HTTP request first, and if
  that's blocked or comes back with no price, falls back to rendering the
  page in a real headless browser (Playwright/Chromium). This fixed most
  sites that 403 plain requests, and sites that need JS to render price.
  It's slower (~3-5s/page vs ~0.5s) and adds a browser-install step to the
  CI workflow.
- **Harbor Freight and O'Reilly are not scrapable and won't be made to
  work here.** Both serve an active "Press & Hold" human-verification
  challenge (PerimeterX/HUMAN Security) to automated traffic, including
  headless browsers — this is a deliberate bot gate, not a passive block,
  and scripting a way past it isn't something this project will do. Items
  recommending those retailers keep the option listed (so you can click
  through and check manually) but it'll permanently show "not found" on
  the dashboard; rely on the Amazon/alternative option tracked alongside
  it instead.
- AutoZone product links may resolve to a region-selector interstitial
  instead of the product page in a headless browser; Home Depot links can
   404 to a generic error page if the URL has gone stale. Both show up as
  "not found" the same way — worth spot-checking those specific links by
  hand if you're relying on that option's price.
- Set `debug: true` when running the workflow manually (Actions tab →
  "Track prices" → Run workflow) to log the page title and a body snippet
  for every option that still comes back with no price — useful for
  telling "this site blocks bots" apart from "the price is on the page in
  a format the extractors don't recognize yet."
- Every run only appends a new reading if a price was successfully found,
  so a temporarily-broken site won't erase history, it'll just show a gap.
- All history lives in `docs/data.json`, committed to your repo — you own
  the data and can inspect/edit it directly if needed.
