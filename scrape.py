#!/usr/bin/env python3
"""
Price tracker scraper.

Reads items.yml. Each item can list several `options` — different
retailers/brands for the same tool — and this script price-checks every
option's URL. For each URL it first tries a plain HTTP GET (fast), and if
that's blocked (403, no price found) it falls back to rendering the page
in a real headless browser via Playwright — several of the retailers this
list uses (Harbor Freight, Home Depot, AutoZone, O'Reilly) return 403 to
plain requests, and Amazon commonly needs JS rendering to expose price.

Either way, the page is searched for a price, in order:
  1. A user-supplied CSS selector (options[].selector)
  2. JSON-LD structured data (schema.org Product/Offer)
  3. Common meta tags (og:price:amount, product:price:amount, itemprop=price)
  4. A generic regex fallback near common "price" class names

Appends a timestamped reading per option to docs/data.json, which the
dashboard (docs/index.html) reads directly. Designed to run on a schedule
via GitHub Actions (see .github/workflows/track-prices.yml).
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
ITEMS_FILE = ROOT / "items.yml"
DATA_FILE = ROOT / "docs" / "data.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

PRICE_RE = re.compile(r"[\$£€]\s?(\d[\d,]*\.?\d{0,2})")


def load_items():
    with open(ITEMS_FILE) as f:
        config = yaml.safe_load(f) or {}
    return config.get("items", [])


def load_history():
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}


def save_history(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def parse_price_str(text):
    if not text:
        return None
    match = PRICE_RE.search(text)
    if not match:
        # try plain number as last resort
        match = re.search(r"\d[\d,]*\.\d{2}", text)
    if not match:
        return None
    raw = match.group(1) if match.groups() else match.group(0)
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def try_selector(soup, selector):
    if not selector:
        return None
    el = soup.select_one(selector)
    if not el:
        return None
    return parse_price_str(el.get_text(strip=True))


def try_json_ld(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else [data]
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            offers = entry.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                price = offers.get("price") or offers.get("lowPrice")
                if price:
                    try:
                        return float(str(price).replace(",", ""))
                    except ValueError:
                        continue
    return None


def try_meta_tags(soup):
    meta_candidates = [
        ("meta", {"property": "og:price:amount"}),
        ("meta", {"property": "product:price:amount"}),
        ("meta", {"itemprop": "price"}),
    ]
    for tag, attrs in meta_candidates:
        el = soup.find(tag, attrs=attrs)
        if el and el.get("content"):
            try:
                return float(el["content"].replace(",", ""))
            except ValueError:
                continue
    return None


def try_generic_fallback(soup):
    for el in soup.select('[class*="price"], [id*="price"]'):
        price = parse_price_str(el.get_text(strip=True))
        if price:
            return price
    return None


def run_extractors(soup, selector):
    for extractor in (
        lambda s: try_selector(s, selector),
        try_json_ld,
        try_meta_tags,
        try_generic_fallback,
    ):
        price = extractor(soup)
        if price is not None:
            return price
    return None


def fetch_price_requests(url, selector):
    """Fast path: plain HTTP GET. Returns price, or None if not found/blocked."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    return run_extractors(soup, selector)


def fetch_price_browser(browser, url, selector):
    """Fallback: render with a real headless browser (defeats most bot-blocking
    and picks up JS-rendered prices plain requests can't see)."""
    page = browser.new_page(
        user_agent=HEADERS["User-Agent"],
        extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
    )
    try:
        page.goto(url, timeout=30000, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)  # let JS-rendered price settle
        html = page.content()
        title = page.title()
    finally:
        page.close()
    soup = BeautifulSoup(html, "lxml")
    price = run_extractors(soup, selector)
    if price is None and os.environ.get("SCRAPE_DEBUG"):
        body_text = soup.get_text(" ", strip=True)[:300]
        print(f"    [debug] title={title!r} html_len={len(html)} body_start={body_text!r}")
    return price


def fetch_price(browser, url, selector=None):
    price = fetch_price_requests(url, selector)
    if price is not None:
        return price
    return fetch_price_browser(browser, url, selector)


def main():
    items = load_items()
    history = load_history()
    now = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for item in items:
                name = item["name"]
                options = item.get("options") or []

                record = history.setdefault(name, {"options": {}})
                record["category"] = item.get("category")
                record["priority"] = item.get("priority")
                record["qty"] = item.get("qty", 1)
                record["budget"] = item.get("budget")
                record["recommended"] = item.get("recommended")
                record["notes"] = item.get("notes")

                if not options:
                    print(f"[skip] {name}: no options configured yet")
                    continue

                for opt in options:
                    label = opt["label"]
                    url = opt["url"]
                    selector = opt.get("selector")

                    opt_record = record["options"].setdefault(
                        label, {"url": url, "history": [], "status": "ok", "error": None}
                    )
                    opt_record["url"] = url  # keep in sync if url changes in items.yml

                    try:
                        price = fetch_price(browser, url, selector)
                        if price is None:
                            opt_record["status"] = "not_found"
                            opt_record["error"] = "Could not locate a price on the page."
                            print(f"[warn] {name} / {label}: no price found")
                        else:
                            opt_record["history"].append({"date": now, "price": price})
                            opt_record["status"] = "ok"
                            opt_record["error"] = None
                            print(f"[ok] {name} / {label}: {price}")
                    except PlaywrightError as e:
                        opt_record["status"] = "error"
                        opt_record["error"] = str(e)
                        print(f"[error] {name} / {label}: {e}")

                    time.sleep(2)  # be polite between requests
        finally:
            browser.close()

    save_history(history)


if __name__ == "__main__":
    sys.exit(main())
