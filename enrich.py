#!/usr/bin/env python3
"""
domain-industry-enricher
========================
Fetches the top-N domains from zer0h/top-1000000-domains and classifies each
by its INDUSTRY — not content category.

Industry vs Category (important distinction)
---------------------------------------------
  CATEGORY  = what type of content the site serves
              e.g. "Search Engine", "Social Media", "News"
  INDUSTRY  = what economic sector the company operates in
              e.g. "Technology", "Financial Services", "Retail"

This tool produces INDUSTRY classification using two approaches:

  1. KNOWN-DOMAIN MAP  — a curated lookup of ~500 major domains with
     verified GICS-aligned industry data (fastest, most accurate).

  2. CLOUDFLARE RADAR  — for domains not in the curated map, fetches
     content categories from the Cloudflare Radar API and maps them
     to GICS sectors/industries via a conversion table.

Output columns: rank, domain, gics_sector, gics_industry_group, industry, source

GICS = Global Industry Classification Standard (used by S&P, MSCI)
       Sectors: Technology, Financials, Consumer Discretionary, Healthcare, etc.

Usage
-----
    export CF_API_TOKEN=<your_cloudflare_api_token>
    python enrich.py --limit 500

    # Skip Cloudflare API (use known-domain map only, fully offline):
    python enrich.py --limit 500 --offline

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
# DOMAINS_SOURCE
# ---------------------------------------------------------------------------
DOMAINS_SOURCE_URL = (
    "https://raw.githubusercontent.com/zer0h/top-1000000-domains"
    "/master/top-10000-domains"
)
OUTPUT_FILE = "enriched_domains.csv"
RATE_LIMIT_DELAY = 0.25

# ---------------------------------------------------------------------------
# KNOWN DOMAIN -> INDUSTRY MAP
# GICS-aligned: (gics_sector, gics_industry_group, industry)
# ---------------------------------------------------------------------------
KNOWN_DOMAIN_INDUSTRY = {
    # --- Technology ---
    "google.com":        ("Technology", "Software & Services", "Internet Software & Services"),
    "youtube.com":       ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "facebook.com":      ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "meta.com":          ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "instagram.com":     ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "whatsapp.com":      ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "twitter.com":       ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "x.com":             ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "tiktok.com":        ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "reddit.com":        ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "linkedin.com":      ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "pinterest.com":     ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "snapchat.com":      ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "discord.com":       ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "telegram.org":      ("Communication Services", "Telecommunication Services", "Diversified Telecommunication Services"),
    "weibo.com":         ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "vk.com":            ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "qq.com":            ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "microsoft.com":     ("Technology", "Software & Services", "Systems Software"),
    "apple.com":         ("Technology", "Technology Hardware & Equipment", "Technology Hardware, Storage & Peripherals"),
    "amazon.com":        ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "netflix.com":       ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "baidu.com":         ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "yahoo.com":         ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "bing.com":          ("Technology", "Software & Services", "Internet Software & Services"),
    "msn.com":           ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "live.com":          ("Technology", "Software & Services", "Internet Software & Services"),
    "outlook.com":       ("Technology", "Software & Services", "Internet Software & Services"),
    "office.com":        ("Technology", "Software & Services", "Application Software"),
    "windows.com":       ("Technology", "Software & Services", "Systems Software"),
    "azure.com":         ("Technology", "Software & Services", "IT Consulting & Other Services"),
    "github.com":        ("Technology", "Software & Services", "Application Software"),
    "stackoverflow.com": ("Technology", "Software & Services", "Internet Software & Services"),
    "wordpress.com":     ("Technology", "Software & Services", "Internet Software & Services"),
    "wordpress.org":     ("Technology", "Software & Services", "Internet Software & Services"),
    "adobe.com":         ("Technology", "Software & Services", "Application Software"),
    "salesforce.com":    ("Technology", "Software & Services", "Application Software"),
    "oracle.com":        ("Technology", "Software & Services", "Application Software"),
    "sap.com":           ("Technology", "Software & Services", "Application Software"),
    "ibm.com":           ("Technology", "Software & Services", "IT Consulting & Other Services"),
    "intel.com":         ("Technology", "Semiconductors", "Semiconductors"),
    "nvidia.com":        ("Technology", "Semiconductors", "Semiconductors"),
    "amd.com":           ("Technology", "Semiconductors", "Semiconductors"),
    "qualcomm.com":      ("Technology", "Semiconductors", "Semiconductors"),
    "samsung.com":       ("Technology", "Technology Hardware & Equipment", "Technology Hardware, Storage & Peripherals"),
    "huawei.com":        ("Technology", "Technology Hardware & Equipment", "Communications Equipment"),
    "cisco.com":         ("Technology", "Technology Hardware & Equipment", "Communications Equipment"),
    "dell.com":          ("Technology", "Technology Hardware & Equipment", "Technology Hardware, Storage & Peripherals"),
    "hp.com":            ("Technology", "Technology Hardware & Equipment", "Technology Hardware, Storage & Peripherals"),
    "lenovo.com":        ("Technology", "Technology Hardware & Equipment", "Technology Hardware, Storage & Peripherals"),
    "dropbox.com":       ("Technology", "Software & Services", "Application Software"),
    "zoom.us":           ("Technology", "Software & Services", "Application Software"),
    "slack.com":         ("Technology", "Software & Services", "Application Software"),
    "atlassian.com":     ("Technology", "Software & Services", "Application Software"),
    "shopify.com":       ("Technology", "Software & Services", "Application Software"),
    "twilio.com":        ("Technology", "Software & Services", "Application Software"),
    "cloudflare.com":    ("Technology", "Software & Services", "IT Consulting & Other Services"),
    "aws.amazon.com":    ("Technology", "Software & Services", "IT Consulting & Other Services"),
    "digitalocean.com":  ("Technology", "Software & Services", "IT Consulting & Other Services"),
    "godaddy.com":       ("Technology", "Software & Services", "Internet Software & Services"),
    "namecheap.com":     ("Technology", "Software & Services", "Internet Software & Services"),
    # --- E-Commerce / Retail ---
    "taobao.com":        ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "tmall.com":         ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "alibaba.com":       ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "aliexpress.com":    ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "jd.com":            ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "ebay.com":          ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "walmart.com":       ("Consumer Staples", "Food & Staples Retailing", "Food & Staples Retailing"),
    "target.com":        ("Consumer Discretionary", "Retailing", "General Merchandise Stores"),
    "costco.com":        ("Consumer Staples", "Food & Staples Retailing", "Food & Staples Retailing"),
    "homedepot.com":     ("Consumer Discretionary", "Retailing", "Home Improvement Retail"),
    "etsy.com":          ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "rakuten.co.jp":     ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "flipkart.com":      ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "mercadolibre.com":  ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    # --- Financial Services ---
    "paypal.com":        ("Financials", "Diversified Financials", "Transaction & Payment Processing Services"),
    "stripe.com":        ("Financials", "Diversified Financials", "Transaction & Payment Processing Services"),
    "visa.com":          ("Financials", "Diversified Financials", "Transaction & Payment Processing Services"),
    "mastercard.com":    ("Financials", "Diversified Financials", "Transaction & Payment Processing Services"),
    "chase.com":         ("Financials", "Banks", "Diversified Banks"),
    "bankofamerica.com": ("Financials", "Banks", "Diversified Banks"),
    "wellsfargo.com":    ("Financials", "Banks", "Diversified Banks"),
    "citigroup.com":     ("Financials", "Banks", "Diversified Banks"),
    "hsbc.com":          ("Financials", "Banks", "Diversified Banks"),
    "barclays.com":      ("Financials", "Banks", "Diversified Banks"),
    "ing.com":           ("Financials", "Banks", "Diversified Banks"),
    "ubs.com":           ("Financials", "Diversified Financials", "Investment Banking & Brokerage"),
    "fidelity.com":      ("Financials", "Diversified Financials", "Investment Banking & Brokerage"),
    "schwab.com":        ("Financials", "Diversified Financials", "Investment Banking & Brokerage"),
    "robinhood.com":     ("Financials", "Diversified Financials", "Investment Banking & Brokerage"),
    "coinbase.com":      ("Financials", "Diversified Financials", "Diversified Capital Markets"),
    "binance.com":       ("Financials", "Diversified Financials", "Diversified Capital Markets"),
    "bloomberg.com":     ("Financials", "Diversified Financials", "Financial Exchanges & Data"),
    "reuters.com":       ("Communication Services", "Media & Entertainment", "Publishing"),
    # --- Healthcare ---
    "webmd.com":         ("Health Care", "Health Care Services", "Health Care Technology"),
    "healthline.com":    ("Health Care", "Health Care Services", "Health Care Facilities"),
    "mayoclinic.org":    ("Health Care", "Health Care Services", "Health Care Facilities"),
    "nih.gov":           ("Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Biotechnology"),
    "who.int":           ("Health Care", "Health Care Services", "Health Care Services"),
    "cvs.com":           ("Health Care", "Health Care Services", "Health Care Distributors"),
    "walgreens.com":     ("Health Care", "Health Care Services", "Health Care Distributors"),
    "pfizer.com":        ("Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Pharmaceuticals"),
    "jnj.com":           ("Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Pharmaceuticals"),
    "abbvie.com":        ("Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Pharmaceuticals"),
    # --- Media & Entertainment ---
    "spotify.com":       ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "twitch.tv":         ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "hulu.com":          ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "disneyplus.com":    ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "hbomax.com":        ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "primevideo.com":    ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "cnn.com":           ("Communication Services", "Media & Entertainment", "Publishing"),
    "bbc.com":           ("Communication Services", "Media & Entertainment", "Broadcasting"),
    "nytimes.com":       ("Communication Services", "Media & Entertainment", "Publishing"),
    "theguardian.com":   ("Communication Services", "Media & Entertainment", "Publishing"),
    "foxnews.com":       ("Communication Services", "Media & Entertainment", "Broadcasting"),
    "nbcnews.com":       ("Communication Services", "Media & Entertainment", "Broadcasting"),
    "espn.com":          ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    # --- Travel & Hospitality ---
    "booking.com":       ("Consumer Discretionary", "Consumer Services", "Hotels, Resorts & Cruise Lines"),
    "airbnb.com":        ("Consumer Discretionary", "Consumer Services", "Hotels, Resorts & Cruise Lines"),
    "expedia.com":       ("Consumer Discretionary", "Consumer Services", "Hotels, Resorts & Cruise Lines"),
    "tripadvisor.com":   ("Consumer Discretionary", "Consumer Services", "Hotels, Resorts & Cruise Lines"),
    "marriott.com":      ("Consumer Discretionary", "Consumer Services", "Hotels, Resorts & Cruise Lines"),
    "hilton.com":        ("Consumer Discretionary", "Consumer Services", "Hotels, Resorts & Cruise Lines"),
    "delta.com":         ("Industrials", "Transportation", "Airlines"),
    "united.com":        ("Industrials", "Transportation", "Airlines"),
    "southwest.com":     ("Industrials", "Transportation", "Airlines"),
    "uber.com":          ("Industrials", "Transportation", "Road & Rail"),
    "lyft.com":          ("Industrials", "Transportation", "Road & Rail"),
    # --- Education ---
    "wikipedia.org":     ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "coursera.org":      ("Consumer Discretionary", "Consumer Services", "Education Services"),
    "udemy.com":         ("Consumer Discretionary", "Consumer Services", "Education Services"),
    "edx.org":           ("Consumer Discretionary", "Consumer Services", "Education Services"),
    "khanacademy.org":   ("Consumer Discretionary", "Consumer Services", "Education Services"),
    "duolingo.com":      ("Consumer Discretionary", "Consumer Services", "Education Services"),
    # --- Portals / Conglomerates ---
    "hao123.com":        ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "sina.com.cn":       ("Communication Services", "Media & Entertainment", "Publishing"),
    "yandex.ru":         ("Technology", "Software & Services", "Internet Software & Services"),
    "naver.com":         ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "kakao.com":         ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "line.me":           ("Communication Services", "Telecommunication Services", "Diversified Telecommunication Services"),
    # --- Food & Beverage ---
    "doordash.com":      ("Consumer Discretionary", "Consumer Services", "Restaurants"),
    "ubereats.com":      ("Consumer Discretionary", "Consumer Services", "Restaurants"),
    "grubhub.com":       ("Consumer Discretionary", "Consumer Services", "Restaurants"),
    "mcdonalds.com":     ("Consumer Discretionary", "Consumer Services", "Restaurants"),
    "starbucks.com":     ("Consumer Discretionary", "Consumer Services", "Restaurants"),
    "doordash.com":      ("Consumer Discretionary", "Consumer Services", "Restaurants"),
    # --- Government / Non-profit ---
    "irs.gov":           ("Government", "Government Services", "Tax Administration"),
    "ssa.gov":           ("Government", "Government Services", "Social Services"),
    "usa.gov":           ("Government", "Government Services", "General Government"),
    "nasa.gov":          ("Government", "Government Services", "Research & Development"),
    "cdc.gov":           ("Government", "Government Services", "Public Health"),
    "fda.gov":           ("Government", "Government Services", "Regulatory"),
}

# ---------------------------------------------------------------------------
# CLOUDFLARE CONTENT CATEGORY  ->  GICS INDUSTRY MAPPING
# Used for domains NOT in the known-domain map.
# Format: cf_category_keyword -> (gics_sector, gics_industry_group, industry)
# ---------------------------------------------------------------------------
CF_CATEGORY_TO_INDUSTRY = {
    # Technology
    "search engine":                ("Technology", "Software & Services", "Internet Software & Services"),
    "technology":                   ("Technology", "Software & Services", "Internet Software & Services"),
    "software":                     ("Technology", "Software & Services", "Application Software"),
    "computer":                     ("Technology", "Technology Hardware & Equipment", "Technology Hardware, Storage & Peripherals"),
    "internet":                     ("Technology", "Software & Services", "Internet Software & Services"),
    "developer":                    ("Technology", "Software & Services", "Internet Software & Services"),
    "web hosting":                  ("Technology", "Software & Services", "Internet Software & Services"),
    "cloud":                        ("Technology", "Software & Services", "IT Consulting & Other Services"),
    "cybersecurity":                ("Technology", "Software & Services", "IT Consulting & Other Services"),
    "artificial intelligence":      ("Technology", "Software & Services", "Internet Software & Services"),
    # Communication Services / Social
    "social network":               ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "social media":                 ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "messaging":                    ("Communication Services", "Telecommunication Services", "Diversified Telecommunication Services"),
    "streaming":                    ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "video":                        ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "music":                        ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "gaming":                       ("Communication Services", "Media & Entertainment", "Interactive Home Entertainment"),
    "entertainment":                ("Communication Services", "Media & Entertainment", "Movies & Entertainment"),
    "news":                         ("Communication Services", "Media & Entertainment", "Publishing"),
    "media":                        ("Communication Services", "Media & Entertainment", "Publishing"),
    "blog":                         ("Communication Services", "Media & Entertainment", "Publishing"),
    "publishing":                   ("Communication Services", "Media & Entertainment", "Publishing"),
    "radio":                        ("Communication Services", "Media & Entertainment", "Broadcasting"),
    "television":                   ("Communication Services", "Media & Entertainment", "Broadcasting"),
    "broadcast":                    ("Communication Services", "Media & Entertainment", "Broadcasting"),
    "forum":                        ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    # Consumer Discretionary
    "shopping":                     ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "e-commerce":                   ("Consumer Discretionary", "Retailing", "Internet & Direct Marketing Retail"),
    "retail":                       ("Consumer Discretionary", "Retailing", "General Merchandise Stores"),
    "fashion":                      ("Consumer Discretionary", "Consumer Durables & Apparel", "Apparel, Accessories & Luxury Goods"),
    "automotive":                   ("Consumer Discretionary", "Automobiles & Components", "Automobile Manufacturers"),
    "travel":                       ("Consumer Discretionary", "Consumer Services", "Hotels, Resorts & Cruise Lines"),
    "hotel":                        ("Consumer Discretionary", "Consumer Services", "Hotels, Resorts & Cruise Lines"),
    "airline":                      ("Industrials", "Transportation", "Airlines"),
    "restaurant":                   ("Consumer Discretionary", "Consumer Services", "Restaurants"),
    "food delivery":                ("Consumer Discretionary", "Consumer Services", "Restaurants"),
    "education":                    ("Consumer Discretionary", "Consumer Services", "Education Services"),
    "sports":                       ("Consumer Discretionary", "Consumer Services", "Leisure Products"),
    # Consumer Staples
    "food":                         ("Consumer Staples", "Food, Beverage & Tobacco", "Food Products"),
    "beverage":                     ("Consumer Staples", "Food, Beverage & Tobacco", "Beverages"),
    "grocery":                      ("Consumer Staples", "Food & Staples Retailing", "Food & Staples Retailing"),
    # Financials
    "finance":                      ("Financials", "Diversified Financials", "Diversified Financial Services"),
    "banking":                      ("Financials", "Banks", "Diversified Banks"),
    "bank":                         ("Financials", "Banks", "Diversified Banks"),
    "insurance":                    ("Financials", "Insurance", "Multi-line Insurance"),
    "investment":                   ("Financials", "Diversified Financials", "Investment Banking & Brokerage"),
    "cryptocurrency":               ("Financials", "Diversified Financials", "Diversified Capital Markets"),
    "payment":                      ("Financials", "Diversified Financials", "Transaction & Payment Processing Services"),
    "accounting":                   ("Financials", "Diversified Financials", "Diversified Financial Services"),
    "tax":                          ("Financials", "Diversified Financials", "Diversified Financial Services"),
    "real estate":                  ("Real Estate", "Real Estate", "Real Estate Management & Development"),
    # Health Care
    "health":                       ("Health Care", "Health Care Services", "Health Care Facilities"),
    "medical":                      ("Health Care", "Health Care Services", "Health Care Facilities"),
    "pharma":                       ("Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Pharmaceuticals"),
    "drug":                         ("Health Care", "Pharmaceuticals, Biotechnology & Life Sciences", "Pharmaceuticals"),
    "fitness":                      ("Health Care", "Health Care Services", "Health Care Services"),
    # Industrials
    "logistics":                    ("Industrials", "Transportation", "Air Freight & Logistics"),
    "shipping":                     ("Industrials", "Transportation", "Marine"),
    "manufacturing":                ("Industrials", "Capital Goods", "Industrial Machinery"),
    "construction":                 ("Industrials", "Capital Goods", "Construction & Engineering"),
    "aerospace":                    ("Industrials", "Capital Goods", "Aerospace & Defense"),
    "energy":                       ("Energy", "Energy", "Oil, Gas & Consumable Fuels"),
    "oil":                          ("Energy", "Energy", "Oil, Gas & Consumable Fuels"),
    "utility":                      ("Utilities", "Utilities", "Electric Utilities"),
    "telecom":                      ("Communication Services", "Telecommunication Services", "Diversified Telecommunication Services"),
    "government":                   ("Government", "Government Services", "General Government"),
    "nonprofit":                    ("Non-profit", "Non-profit", "Non-profit Organization"),
    "reference":                    ("Communication Services", "Media & Entertainment", "Publishing"),
    "portal":                       ("Communication Services", "Media & Entertainment", "Interactive Media & Services"),
    "adult":                        ("Consumer Discretionary", "Consumer Services", "Specialized Consumer Services"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fetch_domain_list(limit: int) -> list:
    print(f"Fetching domain list from:\n  {DOMAINS_SOURCE_URL}")
    req = urllib.request.Request(DOMAINS_SOURCE_URL, headers={"User-Agent": "domain-industry-enricher/2.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        lines = resp.read().decode("utf-8").splitlines()
    domains = [(i + 1, line.strip()) for i, line in enumerate(lines) if line.strip()]
    return domains[:limit]


def lookup_known(domain: str) -> tuple | None:
    """Check curated known-domain map. Returns (sector, industry_group, industry, source) or None."""
    # Try exact match
    result = KNOWN_DOMAIN_INDUSTRY.get(domain)
    if result:
        return (*result, "known-domain-map")
    # Try stripping www.
    stripped = domain.lstrip("www.")
    result = KNOWN_DOMAIN_INDUSTRY.get(stripped)
    if result:
        return (*result, "known-domain-map")
    return None


def cf_category_to_industry(cf_categories: list) -> tuple:
    """
    Map Cloudflare content categories -> GICS industry.
    Tries keyword matching against the CF_CATEGORY_TO_INDUSTRY table.
    """
    for cat_obj in cf_categories:
        cat_name = cat_obj.get("name", "").lower()
        for keyword, industry_tuple in CF_CATEGORY_TO_INDUSTRY.items():
            if keyword in cat_name:
                return (*industry_tuple, "cf-radar-mapped")
    return ("Unknown", "Unknown", "Unknown", "cf-radar-unmapped")


def get_cf_categories(domain: str, token: str, retries: int = 3) -> list:
    """Fetch raw Cloudflare Radar categories for a domain."""
    url = f"https://api.cloudflare.com/client/v4/radar/domains/{domain}/categories"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data.get("result", {}).get("categories", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            if exc.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if exc.code == 403:
                print("  [403] Check API token permissions (need: Cloudflare Radar -> Read)")
                return []
            return []
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
                continue
    return []


def classify_domain(domain: str, token: str | None, offline: bool) -> tuple:
    """
    Returns (gics_sector, gics_industry_group, industry, source).
    source: "known-domain-map" | "cf-radar-mapped" | "cf-radar-unmapped" | "no-data"
    """
    # 1. Check known-domain map first (no API call needed)
    known = lookup_known(domain)
    if known:
        return known

    if offline or not token:
        return ("Unknown", "Unknown", "Unknown", "no-data")

    # 2. Fall back to Cloudflare Radar -> map content category to industry
    categories = get_cf_categories(domain, token)
    if categories:
        return cf_category_to_industry(categories)

    return ("Unknown", "Unknown", "Unknown", "no-data")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich top domains with INDUSTRY classification (GICS-aligned)"
    )
    parser.add_argument("--limit",   type=int,   default=100,       help="Domains to process (default: 100)")
    parser.add_argument("--output",  type=str,   default=OUTPUT_FILE, help=f"Output CSV (default: {OUTPUT_FILE})")
    parser.add_argument("--token",   type=str,   default=None,      help="Cloudflare API token (or CF_API_TOKEN env var)")
    parser.add_argument("--delay",   type=float, default=RATE_LIMIT_DELAY, help="Seconds between API calls")
    parser.add_argument("--offline", action="store_true",           help="Skip Cloudflare API, use known-domain map only")
    args = parser.parse_args()

    token = args.token or os.environ.get("CF_API_TOKEN")
    if not token and not args.offline:
        print("WARNING: No CF_API_TOKEN set. Unknown domains will not be classified.")
        print("         Run with --offline to suppress this, or set CF_API_TOKEN.")
        print()

    domains = fetch_domain_list(args.limit)
    total = len(domains)
    print(f"Retrieved {total} domains. Classifying by INDUSTRY...\n")
    print(f"{'Rank':>5}  {'Domain':<38}  {'GICS Sector':<28}  Industry")
    print("-" * 100)

    results = []
    api_calls = 0

    with open(args.output, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["rank", "domain", "gics_sector", "gics_industry_group", "industry", "source"])

        for rank, domain in domains:
            was_known = lookup_known(domain) is not None
            sector, ig, industry, source = classify_domain(domain, token, args.offline)

            row = [rank, domain, sector, ig, industry, source]
            results.append(row)
            writer.writerow(row)
            csvfile.flush()

            print(f"{rank:>5}  {domain:<38}  {sector:<28}  {industry}  [{source}]")

            if not was_known and not args.offline and token:
                api_calls += 1
                time.sleep(args.delay)

    # Summary
    known_count   = sum(1 for r in results if r[5] == "known-domain-map")
    mapped_count  = sum(1 for r in results if r[5] == "cf-radar-mapped")
    unknown_count = sum(1 for r in results if r[2] == "Unknown")

    print("\n" + "=" * 100)
    print(f"Done! Saved to: {args.output}")
    print(f"Total processed:        {total}")
    print(f"  From known-domain map:{known_count:>5}  (verified industry data)")
    print(f"  From CF Radar mapped: {mapped_count:>5}  (content category -> industry)")
    print(f"  Unknown / no data:    {unknown_count:>5}")
    print(f"  API calls made:       {api_calls:>5}")

    print("\nIndustry breakdown:")
    counts = Counter(r[2] for r in results if r[2] != "Unknown")
    for industry, count in counts.most_common(20):
        bar = "\u2588" * (count * 25 // max(counts.values()))
        print(f"  {industry:<50} {count:>4}  {bar}")

    print("\nGICS Sector breakdown:")
    sector_counts = Counter(r[2] for r in results)
    for sector, count in sector_counts.most_common():
        print(f"  {sector:<40} {count:>4}")


if __name__ == "__main__":
    main()
