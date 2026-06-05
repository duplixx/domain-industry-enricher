# domain-industry-enricher  v3

> Classify top domains by **INDUSTRY** (not content category) using a 3-tier pipeline:
> **Known-Domain Map → Cloudflare Radar → Gemini Flash**

---

## The Core Insight

Most tools (including Cloudflare Radar) give you **content categories**:

> google.com → `Search Engine`
> amazon.com → `Shopping`
> chase.com  → `Financial Services`

These describe *what the website does*. But **industry classification** describes *what economic sector the company operates in*, using standards like GICS (used by S&P 500 and MSCI):

> google.com → **Technology** / Software & Services / *Internet Software & Services*
> amazon.com → **Consumer Discretionary** / Retailing / *Internet & Direct Marketing Retail*
> chase.com  → **Financials** / Banks / *Diversified Banks*

The problem: no free API gives you GICS directly.
**The solution:** use Cloudflare's free content categories as *input context*, then let Gemini Flash do the reasoning to map them to the correct GICS industry.

---

## Pipeline Architecture

```
zer0h/top-10000-domains  (plain ranked list, ~10k domains)
          |
          v
  ┌─────────────────────────────────────────────────────┐
  │  Tier 1: Known-Domain Map                           │
  │  ~500 major domains, verified GICS, instant, free  │
  │  Covers ~95% of top-100 domains                    │
  └──────────────┬──────────────────────────────────────┘
                 │ unknown domains only
                 v
  ┌─────────────────────────────────────────────────────┐
  │  Tier 2: Cloudflare Radar API  (free)               │
  │  GET /radar/domains/{domain}/categories             │
  │  Returns: ["Shopping", "E-Commerce", ...]           │
  └──────────────┬──────────────────────────────────────┘
                 │ categories passed as context
                 v
  ┌─────────────────────────────────────────────────────┐
  │  Tier 3: Gemini Flash  (free tier, 15 req/min)      │
  │  Prompt: "domain=xyz.com, CF categories=Shopping    │
  │           → classify using GICS"                    │
  │  Returns structured JSON:                           │
  │    { gics_sector, gics_industry_group,              │
  │      industry, confidence, reasoning }              │
  └──────────────┬──────────────────────────────────────┘
                 v
       enriched_domains.csv
```

---

## Why Gemini Instead of a Keyword Table?

A static keyword table (`Shopping → Consumer Discretionary`) breaks on:

| Domain | CF Category | Keyword Table | Gemini (correct) |
|--------|-------------|---------------|-----------------|
| robinhood.com | Financial Services | Financials ✓ | Financials / Investment Banking ✓ |
| chase.com | Financial Services, Banking | Financials ✓ | Financials / Diversified Banks ✓ |
| twitch.tv | Gaming, Video | Consumer Discretionary ✗ | Communication Services / Movies & Entertainment ✓ |
| coursera.org | Education | Consumer Discretionary ✓ | Consumer Discretionary / Education Services ✓ |
| reuters.com | News | Communication Services ✓ | Communication Services / Publishing ✓ |
| shopify.com | Shopping, Technology | Consumer Discretionary ✗ | **Technology / Application Software** ✓ |
| airbnb.com | Travel, Real Estate | Consumer Discretionary ✓ | Consumer Discretionary / Hotels, Resorts & Cruise Lines ✓ |

Gemini understands the **company behind the domain**, not just what words appear in the category name.

---

## Sample Output

| rank | domain | gics_sector | gics_industry_group | industry | confidence | source |
|------|--------|-------------|---------------------|----------|------------|--------|
| 1 | google.com | Technology | Software & Services | Internet Software & Services | high | known-domain-map |
| 6 | amazon.com | Consumer Discretionary | Retailing | Internet & Direct Marketing Retail | high | known-domain-map |
| 28 | github.com | Technology | Software & Services | Application Software | high | known-domain-map |
| 32 | paypal.com | Financials | Diversified Financials | Transaction & Payment Processing Services | high | known-domain-map |
| 87 | shopify.com | Technology | Software & Services | Application Software | high | gemini-inferred |
| 142 | coursera.org | Consumer Discretionary | Consumer Services | Education Services | high | gemini-inferred |
| 203 | reuters.com | Communication Services | Media & Entertainment | Publishing | high | gemini-inferred |

See [sample_output.csv](./sample_output.csv) for the first 40 domains.

---

## Quick Start

### Step 1 — Get API Keys (both free)

**Cloudflare Radar** (provides content categories as context for Gemini):
1. Go to [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Create Token → Custom → Permission: `Cloudflare Radar → Read`

**Gemini Flash** (does the industry classification reasoning):
1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API Key** — free tier gives 15 requests/min, 1M tokens/day

### Step 2 — Run

```bash
git clone https://github.com/duplixx/domain-industry-enricher.git
cd domain-industry-enricher

export CF_API_TOKEN=your_cloudflare_token
export GEMINI_API_KEY=your_gemini_key

# Enrich top 100 domains (~2 minutes)
python enrich.py --limit 100

# Enrich top 1000 domains (skip Cloudflare context, Gemini-only, faster)
python enrich.py --limit 1000 --skip-cf

# Offline only (no API calls, known-domain map only)
python enrich.py --limit 500 --offline
```

### Step 3 — Analyze

```bash
# Sector breakdown
awk -F',' 'NR>1 {print $3}' enriched_domains.csv | sort | uniq -c | sort -rn

# All domains in Financials sector
awk -F',' '$3=="Financials" {print $1, $2, $5}' enriched_domains.csv

# Only Gemini-classified entries
awk -F',' '$7~/gemini/ {print $1, $2, $5}' enriched_domains.csv
```

---

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | 100 | Number of domains to process |
| `--output` | enriched_domains.csv | Output CSV path |
| `--cf-token` | env `CF_API_TOKEN` | Cloudflare API token |
| `--gemini-key` | env `GEMINI_API_KEY` | Gemini API key |
| `--skip-cf` | False | Skip Cloudflare, let Gemini classify from domain name only |
| `--offline` | False | No API calls at all, known-domain map only |

---

## Output CSV Schema

```
rank, domain, gics_sector, gics_industry_group, industry, confidence, source, reasoning
```

| Column | Description |
|--------|-------------|
| `rank` | Traffic rank (1 = most visited) |
| `domain` | Domain name |
| `gics_sector` | GICS Level 1 — 11 sectors (Technology, Financials, etc.) |
| `gics_industry_group` | GICS Level 2 — 25 groups |
| `industry` | GICS Level 3 — 74 industries (most specific) |
| `confidence` | `high` / `medium` / `low` — from Gemini's self-assessment |
| `source` | `known-domain-map` / `gemini-inferred` / `gemini-direct` / `no-data` |
| `reasoning` | One-sentence explanation from Gemini |

---

## How the Gemini Prompt Works

Gemini receives:
```
Domain: shopify.com
Content categories (from Cloudflare Radar): Shopping, Software, E-Commerce

Classify this domain's industry using GICS.
```

And returns:
```json
{
  "gics_sector": "Technology",
  "gics_industry_group": "Software & Services",
  "industry": "Application Software",
  "confidence": "high",
  "reasoning": "Shopify is a SaaS e-commerce platform company — its revenue comes from software subscriptions, not from selling products directly"
}
```

The key: Gemini knows that **Shopify earns money selling software**, not by being a retailer — even though its Cloudflare category says "Shopping".

---

## Cost & Rate Limits

| Service | Free Tier | Cost for 10k domains |
|---------|-----------|---------------------|
| Cloudflare Radar | 1,200 req/min | Free |
| Gemini Flash (`gemini-2.0-flash`) | 15 req/min, 1M tokens/day | Free |

Processing 10,000 domains with both APIs: ~12 hours on free tier, or ~2 hours with `--skip-cf`.

---

## Requirements

Python 3.8+ — **no third-party packages required**. Uses only the standard library.

---

## License

MIT — see [LICENSE](./LICENSE)
