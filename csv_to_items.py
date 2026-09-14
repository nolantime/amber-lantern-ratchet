#!/usr/bin/env python3
"""
Regenerate items.yml from the road box CSV.

Reads "C20 Road Box - Sheet1.csv" and writes an items.yml entry for every
row that isn't already marked Purchased. If items.yml already exists,
any `options` (and `selector` overrides within them) already filled in for
a given item name are preserved across regeneration — this script only
manages the metadata columns (category/priority/qty/budget/notes), never
overwrites URLs you've already curated.

Usage:
    python csv_to_items.py [path/to/sheet.csv]
"""

import csv
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
DEFAULT_CSV = ROOT / "C20 Road Box - Sheet1.csv"
ITEMS_FILE = ROOT / "items.yml"


def parse_price(raw):
    if not raw:
        return None
    cleaned = raw.replace("$", "").replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def load_existing_options():
    if not ITEMS_FILE.exists():
        return {}
    with open(ITEMS_FILE) as f:
        config = yaml.safe_load(f) or {}
    return {item["name"]: item.get("options", []) for item in config.get("items", [])}


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CSV
    existing_options = load_existing_options()

    items = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("Purchased", "").strip().upper() == "TRUE":
                continue
            name = row["Item"].strip()
            entry = {
                "name": name,
                "category": row["Category"].strip(),
                "priority": row["Priority"].strip(),
                "qty": int(row["Qty"]) if row.get("Qty", "").strip().isdigit() else 1,
            }
            budget = parse_price(row.get("Price", ""))
            if budget is not None:
                entry["budget"] = budget
            brand = row.get("Brand Recommendation", "").strip()
            if brand:
                entry["recommended"] = brand
            notes = row.get("Notes", "").strip()
            if notes:
                entry["notes"] = notes
            entry["options"] = existing_options.get(name, [])
            items.append(entry)

    with open(ITEMS_FILE, "w") as f:
        f.write(
            "# Generated from the CSV by csv_to_items.py — re-run it any time the\n"
            "# CSV changes; it preserves options you've already filled in.\n"
            "#\n"
            "# Each item:\n"
            "#   name / category / priority / qty / budget / notes: from the CSV\n"
            "#   recommended: the CSV's Brand Recommendation, for reference\n"
            "#   options: retailer listings to price-check for this item —\n"
            "#     - label: short name shown on the dashboard, e.g. \"ICON (Harbor Freight)\"\n"
            "#       url: the product page\n"
            "#       selector: optional CSS selector override if auto-detection fails\n"
            "#   Add as many options as you want compared (recommended brand +\n"
            "#   alternatives); leave options: [] until you've found links.\n\n"
        )
        yaml.dump({"items": items}, f, sort_keys=False, allow_unicode=True, width=100)

    unpurchased = len(items)
    missing = sum(1 for i in items if not i["options"])
    print(f"Wrote {unpurchased} items to {ITEMS_FILE} ({missing} still need options).")


if __name__ == "__main__":
    main()
