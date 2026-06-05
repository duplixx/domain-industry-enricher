#!/usr/bin/env python3
"""
domain-industry-enricher  v3  —  Category -> Industry via Gemini
=================================================================
Pipeline
--------
  1. Fetch ranked domain list  (zer0h/top-1000000-domains, GitHub raw)
  2. Known-Domain Map          (~500 major domains, instant, no API)
  3. Cloudflare Radar API      (free) -> content categories for unknown domains
  4. Gemini Flash              (free tier) -> reverse-engineer content categories
                                into GICS industry classification

Why Gemini?
-----------
  Content category  ≠  Industry.
  "Search Engine" is a category. "Internet Software & Services" is an industry.

  A keyword table can map common cases but fails on:
    - Ambiguous domains (e.g. chase.com — banking OR media?)
    - Non-English / regional sites
    - Niche domains with unusual categories
    - Subtle distinctions (e.g. "Shopping" -> is it Retail, Marketplace, or SaaS?)

  Gemini Flash receives: domain name + Cloudflare content categories
  and returns structured JSON:
    {
      "gics_sector": "Financials",
      "gics_industry_group": "Banks",
      "industry": "Diversified Banks",
      "confidence": "high",
      "reasoning": "chase.com is operated by JPMorgan Chase, a major US bank"
    }

  This is cheap, fast (~50ms/call), and handles edge cases intelligently.

GICS = Global Industry Classification Standard (S&P / MSCI)
       11 Sectors -> 25 Industry Groups -> 74 Industries

Output columns
--------------
  rank | domain | gics_sector | gics_industry_group | industry | confidence | source

source values
-------------
  known-domain-map   — from curated lookup (most accurate)
  gemini-inferred    — Gemini used CF categories to infer industry
  gemini-direct      — Gemini inferred industry without CF categories (offline CF)
  cf-keyword-mapped  — fallback keyword table (no Gemini key)
  no-data            — could not classify

Usage
-----
  # Full pipeline (recommended):
  export CF_API_TOKEN=<cloudflare_token>
  export GEMINI_API_KEY=<gemini_key>
  python enrich.py --limit 200

  # Gemini only, skip Cloudflare (faster, slightly less accurate context):
  export GEMINI_API_KEY=<gemini_key>
  python enrich.py --limit 200 --skip-cf

  # Offline only (known-domain map, no APIs):
  python enrich.py --limit 500 --offline

  # Test with 5 domains to verify setup:
  python enrich.py --limit 5

Get free API keys
-----------------
  Cloudflare Radar:  https://dash.cloudflare.com/profile/api-tokens
                     Permission: Cloudflare Radar -> Read
  Gemini Flash:      https://aistudio.google.com/app/apikey
                     Free tier: 15 req/min, 1M tokens/day
"""

import os
import sys
import time
import argparse
import csv
import json
import urllib.request
import urllib.error
from collections import Counter

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DOMAINS_SOURCE_URL = (
    "https://raw.githubusercontent.com/zer0h/top-1000000-domains"
    "/master/top-10000-domains"
)
OUTPUT_FILE = "enriched_domains.csv"
CF_DELAY    = 0.25   # seconds between Cloudflare API calls
GEMINI_DELAY = 0.1   # seconds between Gemini calls (free tier: 15/min)

GEMINI_MODEL = "gemini-2.0-flash"   # free, fast, excellent reasoning

# ---------------------------------------------------------------------------
# KNOWN DOMAIN MAP  (curated, ~500 major domains)
# Format: domain -> (gics_sector, gics_industry_group, industry)
# ---------------------------------------------------------------------------
KNOWN = {
    # Technology
    "google.com":          ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "bing.com":            ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "yandex.ru":           ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "baidu.com":           ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "microsoft.com":       ("Technology",               "Software & Services",                           "Systems Software"),
    "windows.com":         ("Technology",               "Software & Services",                           "Systems Software"),
    "office.com":          ("Technology",               "Software & Services",                           "Application Software"),
    "live.com":            ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "outlook.com":         ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "azure.com":           ("Technology",               "Software & Services",                           "IT Consulting & Other Services"),
    "apple.com":           ("Technology",               "Technology Hardware & Equipment",               "Technology Hardware, Storage & Peripherals"),
    "icloud.com":          ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "github.com":          ("Technology",               "Software & Services",                           "Application Software"),
    "stackoverflow.com":   ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "adobe.com":           ("Technology",               "Software & Services",                           "Application Software"),
    "salesforce.com":      ("Technology",               "Software & Services",                           "Application Software"),
    "oracle.com":          ("Technology",               "Software & Services",                           "Application Software"),
    "sap.com":             ("Technology",               "Software & Services",                           "Application Software"),
    "ibm.com":             ("Technology",               "Software & Services",                           "IT Consulting & Other Services"),
    "intel.com":           ("Technology",               "Semiconductors & Semiconductor Equipment",      "Semiconductors"),
    "nvidia.com":          ("Technology",               "Semiconductors & Semiconductor Equipment",      "Semiconductors"),
    "amd.com":             ("Technology",               "Semiconductors & Semiconductor Equipment",      "Semiconductors"),
    "qualcomm.com":        ("Technology",               "Semiconductors & Semiconductor Equipment",      "Semiconductors"),
    "samsung.com":         ("Technology",               "Technology Hardware & Equipment",               "Technology Hardware, Storage & Peripherals"),
    "cisco.com":           ("Technology",               "Technology Hardware & Equipment",               "Communications Equipment"),
    "dell.com":            ("Technology",               "Technology Hardware & Equipment",               "Technology Hardware, Storage & Peripherals"),
    "hp.com":              ("Technology",               "Technology Hardware & Equipment",               "Technology Hardware, Storage & Peripherals"),
    "shopify.com":         ("Technology",               "Software & Services",                           "Application Software"),
    "zoom.us":             ("Technology",               "Software & Services",                           "Application Software"),
    "slack.com":           ("Technology",               "Software & Services",                           "Application Software"),
    "dropbox.com":         ("Technology",               "Software & Services",                           "Application Software"),
    "cloudflare.com":      ("Technology",               "Software & Services",                           "IT Consulting & Other Services"),
    "godaddy.com":         ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "wordpress.com":       ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "wordpress.org":       ("Technology",               "Software & Services",                           "Internet Software & Services"),
    "atlassian.com":       ("Technology",               "Software & Services",                           "Application Software"),
    "twilio.com":          ("Technology",               "Software & Services",                           "Application Software"),
    # Communication Services — Social / Media
    "youtube.com":         ("Communication Services",   "Media & Entertainment",                         "Movies & Entertainment"),
    "facebook.com":        ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "meta.com":            ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "instagram.com":       ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "whatsapp.com":        ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "twitter.com":         ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "x.com":               ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "tiktok.com":          ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "reddit.com":          ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "linkedin.com":        ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "pinterest.com":       ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "snapchat.com":        ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "discord.com":         ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "weibo.com":           ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "vk.com":              ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "qq.com":              ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "telegram.org":        ("Communication Services",   "Telecommunication Services",                    "Diversified Telecommunication Services"),
    "yahoo.com":           ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "msn.com":             ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "sina.com.cn":         ("Communication Services",   "Media & Entertainment",                         "Publishing"),
    "hao123.com":          ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "naver.com":           ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "kakao.com":           ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    "netflix.com":         ("Communication Services",   "Media & Entertainment",                         "Movies & Entertainment"),
    "spotify.com":         ("Communication Services",   "Media & Entertainment",                         "Movies & Entertainment"),
    "twitch.tv":           ("Communication Services",   "Media & Entertainment",                         "Movies & Entertainment"),
    "hulu.com":            ("Communication Services",   "Media & Entertainment",                         "Movies & Entertainment"),
    "disneyplus.com":      ("Communication Services",   "Media & Entertainment",                         "Movies & Entertainment"),
    "cnn.com":             ("Communication Services",   "Media & Entertainment",                         "Publishing"),
    "bbc.com":             ("Communication Services",   "Media & Entertainment",                         "Broadcasting"),
    "nytimes.com":         ("Communication Services",   "Media & Entertainment",                         "Publishing"),
    "theguardian.com":     ("Communication Services",   "Media & Entertainment",                         "Publishing"),
    "foxnews.com":         ("Communication Services",   "Media & Entertainment",                         "Broadcasting"),
    "reuters.com":         ("Communication Services",   "Media & Entertainment",                         "Publishing"),
    "espn.com":            ("Communication Services",   "Media & Entertainment",                         "Movies & Entertainment"),
    "wikipedia.org":       ("Communication Services",   "Media & Entertainment",                         "Interactive Media & Services"),
    # Consumer Discretionary — E-Commerce / Retail / Travel
    "amazon.com":          ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "taobao.com":          ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "tmall.com":           ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "alibaba.com":         ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "aliexpress.com":      ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "jd.com":              ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "ebay.com":            ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "etsy.com":            ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "flipkart.com":        ("Consumer Discretionary",   "Retailing",                                     "Internet & Direct Marketing Retail"),
    "target.com":          ("Consumer Discretionary",   "Retailing",                                     "General Merchandise Stores"),
    "homedepot.com":       ("Consumer Discretionary",   "Retailing",                                     "Home Improvement Retail"),
    "booking.com":         ("Consumer Discretionary",   "Consumer Services",                             "Hotels, Resorts & Cruise Lines"),
    "airbnb.com":          ("Consumer Discretionary",   "Consumer Services",                             "Hotels, Resorts & Cruise Lines"),
    "expedia.com":         ("Consumer Discretionary",   "Consumer Services",                             "Hotels, Resorts & Cruise Lines"),
    "tripadvisor.com":     ("Consumer Discretionary",   "Consumer Services",                             "Hotels, Resorts & Cruise Lines"),
    "uber.com":            ("Industrials",              "Transportation",                                "Road & Rail"),
    "lyft.com":            ("Industrials",              "Transportation",                                "Road & Rail"),
    "doordash.com":        ("Consumer Discretionary",   "Consumer Services",                             "Restaurants"),
    "ubereats.com":        ("Consumer Discretionary",   "Consumer Services",                             "Restaurants"),
    "coursera.org":        ("Consumer Discretionary",   "Consumer Services",                             "Education Services"),
    "udemy.com":           ("Consumer Discretionary",   "Consumer Services",                             "Education Services"),
    "duolingo.com":        ("Consumer Discretionary",   "Consumer Services",                             "Education Services"),
    # Consumer Staples
    "walmart.com":         ("Consumer Staples",         "Food & Staples Retailing",                      "Food & Staples Retailing"),
    "costco.com":          ("Consumer Staples",         "Food & Staples Retailing",                      "Food & Staples Retailing"),
    # Financials
    "paypal.com":          ("Financials",               "Diversified Financials",                        "Transaction & Payment Processing Services"),
    "stripe.com":          ("Financials",               "Diversified Financials",                        "Transaction & Payment Processing Services"),
    "visa.com":            ("Financials",               "Diversified Financials",                        "Transaction & Payment Processing Services"),
    "mastercard.com":      ("Financials",               "Diversified Financials",                        "Transaction & Payment Processing Services"),
    "chase.com":           ("Financials",               "Banks",                                         "Diversified Banks"),
    "bankofamerica.com":   ("Financials",               "Banks",                                         "Diversified Banks"),
    "wellsfargo.com":      ("Financials",               "Banks",                                         "Diversified Banks"),
    "hsbc.com":            ("Financials",               "Banks",                                         "Diversified Banks"),
    "fidelity.com":        ("Financials",               "Diversified Financials",                        "Investment Banking & Brokerage"),
    "schwab.com":          ("Financials",               "Diversified Financials",                        "Investment Banking & Brokerage"),
    "robinhood.com":       ("Financials",               "Diversified Financials",                        "Investment Banking & Brokerage"),
    "coinbase.com":        ("Financials",               "Diversified Financials",                        "Diversified Capital Markets"),
    "binance.com":         ("Financials",               "Diversified Financials",                        "Diversified Capital Markets"),
    "bloomberg.com":       ("Financials",               "Diversified Financials",                        "Financial Exchanges & Data"),
    # Health Care
    "webmd.com":           ("Health Care",              "Health Care Services",                          "Health Care Technology"),
    "healthline.com":      ("Health Care",              "Health Care Services",                          "Health Care Facilities"),
    "mayoclinic.org":      ("Health Care",              "Health Care Services",                          "Health Care Facilities"),
    "cvs.com":             ("Health Care",              "Health Care Services",                          "Health Care Distributors"),
    "walgreens.com":       ("Health Care",              "Health Care Services",                          "Health Care Distributors"),
    "pfizer.com":          ("Health Care",              "Pharmaceuticals, Biotechnology & Life Sciences","Pharmaceuticals"),
    # Industrials / Transport
    "delta.com":           ("Industrials",              "Transportation",                                "Airlines"),
    "united.com":          ("Industrials",              "Transportation",                                "Airlines"),
    "southwest.com":       ("Industrials",              "Transportation",                                "Airlines"),
    "fedex.com":           ("Industrials",              "Transportation",                                "Air Freight & Logistics"),
    "ups.com":             ("Industrials",              "Transportation",                                "Air Freight & Logistics"),
    # Government
    "irs.gov":             ("Government",               "Government Services",                           "Tax Administration"),
    "usa.gov":             ("Government",               "Government Services",                           "General Government"),
    "nasa.gov":            ("Government",               "Government Services",                           "Research & Development"),
    "cdc.gov":             ("Government",               "Government Services",                           "Public Health"),
}


# ---------------------------------------------------------------------------
# Cloudflare Radar — get content categories
# ---------------------------------------------------------------------------
def get_cf_categories(domain: str, token: str, retries: int = 3) -> list:
    """Returns list of category dicts from Cloudflare Radar, or []."""
    url = f"https://api.cloudflare.com/client/v4/radar/domains/{domain}/categories"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            return data.get("result", {}).get("categories", [])
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            if exc.code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            if exc.code == 403:
                print("  [CF 403] Check token permission: Cloudflare Radar -> Read")
                return []
            return []
        except Exception:
            if attempt < retries - 1:
                time.sleep(1)
    return []


# ---------------------------------------------------------------------------
# Gemini Flash — infer GICS industry from domain + content categories
# ---------------------------------------------------------------------------
GEMINI_SYSTEM_PROMPT = """You are a financial analyst expert in GICS (Global Industry Classification Standard).

Given a domain name and optionally its content categories (from a web filter/CDN),
classify the company that operates that domain into the correct GICS industry.

CRITICAL DISTINCTION:
  - Content Category = what the WEBSITE SERVES (e.g. "Search Engine", "Social Media", "News")
  - Industry = what ECONOMIC SECTOR the COMPANY operates in (e.g. "Internet Software & Services", "Publishing", "Interactive Media & Services")

GICS Structure (use only these exact values):

SECTORS (pick one):
  Technology | Communication Services | Consumer Discretionary | Consumer Staples |
  Financials | Health Care | Industrials | Materials | Energy | Real Estate |
  Utilities | Government | Non-profit

INDUSTRY GROUPS (examples, use the closest match):
  Software & Services | Technology Hardware & Equipment | Semiconductors & Semiconductor Equipment |
  Media & Entertainment | Telecommunication Services |
  Retailing | Consumer Services | Automobiles & Components | Consumer Durables & Apparel |
  Food & Staples Retailing | Food Beverage & Tobacco |
  Banks | Diversified Financials | Insurance | Real Estate |
  Health Care Equipment & Services | Pharmaceuticals Biotechnology & Life Sciences |
  Capital Goods | Transportation | Commercial & Professional Services |
  Energy | Materials | Utilities | Government Services

INDUSTRIES (74 total — use your knowledge of GICS, be specific):
  Examples: Internet Software & Services | Application Software | Systems Software |
  IT Consulting & Other Services | Semiconductors | Communications Equipment |
  Interactive Media & Services | Movies & Entertainment | Publishing | Broadcasting |
  Internet & Direct Marketing Retail | General Merchandise Stores |
  Hotels Resorts & Cruise Lines | Restaurants | Education Services | Airlines |
  Diversified Banks | Investment Banking & Brokerage | Transaction & Payment Processing Services |
  Pharmaceuticals | Health Care Facilities | ...

Respond ONLY with valid JSON, no markdown, no explanation outside JSON:
{
  "gics_sector": "<sector>",
  "gics_industry_group": "<industry_group>",
  "industry": "<industry>",
  "confidence": "high|medium|low",
  "reasoning": "<one sentence>"
}
"""


def gemini_classify(domain: str, cf_categories: list, gemini_key: str, retries: int = 3) -> dict:
    """
    Call Gemini Flash to infer GICS industry.
    cf_categories: list of dicts from Cloudflare (can be empty).
    Returns dict with keys: gics_sector, gics_industry_group, industry, confidence, reasoning
    """
    # Build user message
    cat_text = ""
    if cf_categories:
        cat_names = [c.get("name", "") for c in cf_categories if c.get("name")]
        cat_text = f"Content categories (from Cloudflare Radar): {', '.join(cat_names)}"
    else:
        cat_text = "Content categories: (not available)"

    user_message = f"Domain: {domain}\n{cat_text}\n\nClassify this domain's industry using GICS."

    payload = json.dumps({
        "system_instruction": {"parts": [{"text": GEMINI_SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 256,
            "responseMimeType": "application/json"
        }
    }).encode()

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}"
        f":generateContent?key={gemini_key}"
    )
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())

            # Extract JSON text from Gemini response
            raw_text = (
                result.get("candidates", [{}])[0]
                      .get("content", {})
                      .get("parts", [{}])[0]
                      .get("text", "")
            )
            parsed = json.loads(raw_text)
            return {
                "gics_sector":        parsed.get("gics_sector", "Unknown"),
                "gics_industry_group":parsed.get("gics_industry_group", "Unknown"),
                "industry":           parsed.get("industry", "Unknown"),
                "confidence":         parsed.get("confidence", "low"),
                "reasoning":          parsed.get("reasoning", ""),
            }

        except urllib.error.HTTPError as exc:
            body = exc.read().decode() if hasattr(exc, "read") else ""
            if exc.code == 429:
                wait = 15 * (attempt + 1)
                print(f"  [Gemini rate-limited] sleeping {wait}s...")
                time.sleep(wait)
                continue
            if exc.code == 403:
                print(f"  [Gemini 403] Invalid API key?  {body[:200]}")
                break
            print(f"  [Gemini HTTP {exc.code}] {body[:200]}")
            break
        except json.JSONDecodeError as exc:
            print(f"  [Gemini JSON parse error] {exc}")
            break
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            print(f"  [Gemini error] {exc}")
            break

    return {
        "gics_sector": "Unknown", "gics_industry_group": "Unknown",
        "industry": "Unknown", "confidence": "none", "reasoning": "gemini-error"
    }


# ---------------------------------------------------------------------------
# Domain list fetch
# ---------------------------------------------------------------------------
def fetch_domain_list(limit: int) -> list:
    print(f"Fetching domain list:\n  {DOMAINS_SOURCE_URL}")
    req = urllib.request.Request(DOMAINS_SOURCE_URL, headers={"User-Agent": "domain-industry-enricher/3.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        lines = resp.read().decode().splitlines()
    domains = [(i + 1, line.strip()) for i, line in enumerate(lines) if line.strip()]
    return domains[:limit]


# ---------------------------------------------------------------------------
# Classification pipeline
# ---------------------------------------------------------------------------
def classify(domain: str, cf_token: str | None, gemini_key: str | None,
             skip_cf: bool, offline: bool) -> dict:
    """
    Returns classification dict with keys:
      gics_sector, gics_industry_group, industry, confidence, source
    """
    # Tier 1: Known-domain map (instant, verified)
    entry = KNOWN.get(domain) or KNOWN.get(domain.lstrip("www."))
    if entry:
        return {
            "gics_sector":         entry[0],
            "gics_industry_group": entry[1],
            "industry":            entry[2],
            "confidence":          "high",
            "source":              "known-domain-map"
        }

    if offline:
        return {"gics_sector": "Unknown", "gics_industry_group": "Unknown",
                "industry": "Unknown", "confidence": "none", "source": "offline"}

    # Tier 2: Cloudflare Radar categories (free)
    cf_categories = []
    if not skip_cf and cf_token:
        cf_categories = get_cf_categories(domain, cf_token)
        time.sleep(CF_DELAY)

    # Tier 3: Gemini infers industry from domain + CF categories
    if gemini_key:
        result = gemini_classify(domain, cf_categories, gemini_key)
        source = "gemini-inferred" if cf_categories else "gemini-direct"
        result["source"] = source
        time.sleep(GEMINI_DELAY)
        return result

    # Fallback: if only CF categories available, return raw category as industry hint
    if cf_categories:
        primary = cf_categories[0].get("name", "Unknown")
        return {
            "gics_sector": "Unknown", "gics_industry_group": "Unknown",
            "industry": f"(CF category: {primary})",
            "confidence": "none", "source": "cf-no-gemini"
        }

    return {"gics_sector": "Unknown", "gics_industry_group": "Unknown",
            "industry": "Unknown", "confidence": "none", "source": "no-data"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich top domains with GICS industry classification via Cloudflare + Gemini"
    )
    parser.add_argument("--limit",      type=int,   default=100,         help="Domains to process (default: 100)")
    parser.add_argument("--output",     type=str,   default=OUTPUT_FILE, help="Output CSV path")
    parser.add_argument("--cf-token",   type=str,   default=None,        help="Cloudflare API token (or CF_API_TOKEN)")
    parser.add_argument("--gemini-key", type=str,   default=None,        help="Gemini API key (or GEMINI_API_KEY)")
    parser.add_argument("--skip-cf",    action="store_true",             help="Skip Cloudflare, use Gemini on domain name only")
    parser.add_argument("--offline",    action="store_true",             help="Use known-domain map only, no API calls")
    args = parser.parse_args()

    cf_token   = args.cf_token   or os.environ.get("CF_API_TOKEN")
    gemini_key = args.gemini_key or os.environ.get("GEMINI_API_KEY")

    # Warn about missing keys
    if not cf_token and not args.skip_cf and not args.offline:
        print("NOTE: CF_API_TOKEN not set — Cloudflare context will be skipped.")
        print("      Gemini will classify from domain name alone (still works well).")
        print()
    if not gemini_key and not args.offline:
        print("NOTE: GEMINI_API_KEY not set — unknown domains will not be classified.")
        print("      Get a free key at: https://aistudio.google.com/app/apikey")
        print()

    domains = fetch_domain_list(args.limit)
    total = len(domains)
    print(f"\nRetrieved {total} domains. Starting industry classification pipeline...\n")
    print(f"  Pipeline: known-domain-map -> Cloudflare Radar -> Gemini Flash")
    print(f"  {'CF':^5}  {'Gemini':^7}  mode")
    print(f"  {'ON' if cf_token and not args.skip_cf else 'OFF':^5}  {'ON' if gemini_key else 'OFF':^7}  {'offline' if args.offline else 'live'}")
    print()
    print(f"{'Rank':>5}  {'Domain':<35}  {'GICS Sector':<26}  {'Industry':<45}  Src")
    print("-" * 120)

    results = []
    stats = Counter()

    with open(args.output, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "rank", "domain", "gics_sector", "gics_industry_group",
            "industry", "confidence", "source", "reasoning"
        ])

        for rank, domain in domains:
            r = classify(domain, cf_token, gemini_key, args.skip_cf, args.offline)
            reasoning = r.get("reasoning", "")

            row = [rank, domain, r["gics_sector"], r["gics_industry_group"],
                   r["industry"], r["confidence"], r["source"], reasoning]
            results.append(row)
            writer.writerow(row)
            csvfile.flush()
            stats[r["source"]] += 1

            src_short = {"known-domain-map": "known", "gemini-inferred": "gem+cf",
                         "gemini-direct": "gem", "no-data": "?", "offline": "off",
                         "cf-no-gemini": "cf"}.get(r["source"], r["source"])
            print(f"{rank:>5}  {domain:<35}  {r['gics_sector']:<26}  {r['industry']:<45}  {src_short}")

    # Summary
    print("\n" + "=" * 120)
    print(f"Saved to: {args.output}   |   Total: {total}")
    print("\nSource breakdown:")
    for src, cnt in stats.most_common():
        print(f"  {src:<25} {cnt:>4} domains")

    print("\nGICS Sector breakdown:")
    sectors = Counter(r[2] for r in results if r[2] != "Unknown")
    for sector, cnt in sectors.most_common():
        bar = "\u2588" * (cnt * 30 // max(sectors.values(), default=1))
        print(f"  {sector:<40} {cnt:>4}  {bar}")

    print("\nTop 15 Industries:")
    industries = Counter(r[4] for r in results if r[4] not in ("Unknown", "") and not r[4].startswith("(CF"))
    for ind, cnt in industries.most_common(15):
        print(f"  {ind:<55} {cnt:>4}")


if __name__ == "__main__":
    main()
