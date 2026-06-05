#!/usr/bin/env python3
"""
domain-industry-enricher
========================
Fetches the top-N domains from zer0h/top-1000000-domains and enriches each
with an industry/category label using the Cloudflare Radar API (free tier).

Output: enriched_domains.csv  (rank, domain, category, subcategory)

Usage
-----
    pip install -r requirements.txt
    export CF_API_TOKEN=<your_cloudflare_api_token>
    python enrich.py --limit 100

Get a free Cloudflare API token:
  https://dash.cloudflare.com/profile/api-tokens
  Required permission: "Cloudflare Radar -> Read"
"""

import os
import sys
import time
import argparse
import csv
import urllib.request
import json
from collections import Counter

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DOMAINS_SOURCE_URL = (
    "https://raw.githubusercontent.com/zer0h/top-1000000-domains"
    "/master/top-10000-domains"
)
OUTPUT_FILE = "enriched_domains.csv"
RATE_LIMIT_DELAY = 0.25   # seconds between API calls (~4 req/s)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fetch_domain_list(limit: int) -> list:
    """Download the zer0h top-domains file and return [(rank, domain), ...]."""
    print(f"Fetching domain list from:\n  {DOMAINS_SOURCE_URL}")
    req = urllib.request.Request(DOMAINS_SOURCE_URL, headers={"User-Agent": "domain-enricher/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        lines = resp.read().decode("utf-8").splitlines()
    domains = [(i + 1, line.strip()) for i, line in enumerate(lines) if line.strip()]
    return domains[:limit]


def get_domain_categories(domain: str, token: str, retries: int = 3) -> tuple:
    """
    Query Cloudflare Radar for content categories of a domain.
    Endpoint: GET /client/v4/radar/domains/{domain}/categories
    Returns (primary_category, subcategory).
    """
    url = f"https://api.cloudflare.com/client/v4/radar/domains/{domain}/categories"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            categories = data.get("result", {}).get("categories", [])
            if not categories:
                return "Uncategorized", ""

            primary = categories[0].get("name", "Unknown")
            sub = categories[1].get("name", "") if len(categories) > 1 else ""
            return primary, sub

        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return "Not Found", ""
            if exc.code == 429:
                wait = 5 * (attempt + 1)
                print(f"  [rate-limited] sleeping {wait}s...")
                time.sleep(wait)
                continue
            if exc.code == 403:
                print("  [403 Forbidden] Check your API token permissions.")
                return "Auth Error", ""
            return f"HTTP {exc.code}", ""
        except urllib.error.URLError as exc:
            if attempt < retries - 1:
                time.sleep(1)
                continue
            return f"Network Error", ""
        except Exception as exc:
            return f"Error: {type(exc).__name__}", ""

    return "Max Retries", ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich top domains with industry/category data via Cloudflare Radar"
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Number of domains to process (default: 100)"
    )
    parser.add_argument(
        "--output", type=str, default=OUTPUT_FILE,
        help=f"Output CSV path (default: {OUTPUT_FILE})"
    )
    parser.add_argument(
        "--token", type=str, default=None,
        help="Cloudflare API token (or set CF_API_TOKEN env var)"
    )
    parser.add_argument(
        "--delay", type=float, default=RATE_LIMIT_DELAY,
        help=f"Delay in seconds between API calls (default: {RATE_LIMIT_DELAY})"
    )
    args = parser.parse_args()

    token = args.token or os.environ.get("CF_API_TOKEN")
    if not token:
        print("ERROR: No Cloudflare API token found.")
        print("  Set CF_API_TOKEN env var or pass --token <token>")
        print("  Get one free at: https://dash.cloudflare.com/profile/api-tokens")
        print("  Required permission scope: Cloudflare Radar -> Read")
        sys.exit(1)

    # 1. Fetch domain list
    domains = fetch_domain_list(args.limit)
    total = len(domains)
    print(f"Retrieved {total} domains. Starting Cloudflare Radar enrichment...\n")
    print(f"{'Rank':>5}  {'Domain':<40}  Category")
    print("-" * 80)

    # 2. Enrich & write CSV
    results = []
    with open(args.output, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["rank", "domain", "category", "subcategory"])

        for rank, domain in domains:
            category, subcategory = get_domain_categories(domain, token)
            row = [rank, domain, category, subcategory]
            results.append(row)
            writer.writerow(row)
            csvfile.flush()   # Write incrementally so partial results are saved

            cat_display = category
            if subcategory:
                cat_display += f" / {subcategory}"
            print(f"{rank:>5}  {domain:<40}  {cat_display}")

            time.sleep(args.delay)

    # 3. Summary
    print("\n" + "=" * 80)
    print(f"Done! Results saved to: {args.output}")
    print(f"Total processed: {total}")

    ok = [r for r in results if r[2] not in ("Uncategorized", "Not Found", "Auth Error", "") and not r[2].startswith(("Error", "HTTP", "Network", "Max"))]
    print(f"Categorized:     {len(ok)} / {total} ({100*len(ok)//total}%)")

    print("\nTop categories found:")
    counts = Counter(r[2] for r in results)
    for cat, count in counts.most_common(15):
        bar = "\u2588" * (count * 30 // total)
        print(f"  {cat:<35} {count:>4}  {bar}")


if __name__ == "__main__":
    main()
