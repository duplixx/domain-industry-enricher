# domain-industry-enricher

> **DIY tool to classify top domains by INDUSTRY — not content category.**
> Uses the GICS (Global Industry Classification Standard) used by S&P 500, MSCI, and financial analysts worldwide.

---

## Industry vs Category — Why It Matters

Most domain enrichment tools give you **content categories** — they describe *what the website is about*:

| Domain | Content Category |
|--------|-----------------|
| google.com | Search Engine |
| youtube.com | Video Streaming |
| amazon.com | Shopping |
| cnn.com | News |

This is useful for content filtering. But if you're doing **market research, competitive intelligence, or financial analysis**, you need **industry classification** — *what economic sector does the company operate in*:

| Domain | GICS Sector | Industry Group | Industry |
|--------|-------------|----------------|----------|
| google.com | Technology | Software & Services | Internet Software & Services |
| youtube.com | Communication Services | Media & Entertainment | Movies & Entertainment |
| amazon.com | Consumer Discretionary | Retailing | Internet & Direct Marketing Retail |
| cnn.com | Communication Services | Media & Entertainment | Publishing |

**Industry** answers: *"What business is this company in?"*
**Category** answers: *"What content does this website serve?"*

---

## Classification Standard: GICS

This tool uses **GICS (Global Industry Classification Standard)**, developed by MSCI and S&P. It's the same system used to classify stocks in the S&P 500.

**GICS has 4 levels:**
1. **Sector** (11 total) — Technology, Financials, Health Care, Consumer Discretionary, etc.
2. **Industry Group** (25 total) — Software & Services, Banks, Media & Entertainment, etc.
3. **Industry** (74 total) — Internet Software & Services, Diversified Banks, Publishing, etc.
4. **Sub-Industry** (163 total) — not used here

This tool outputs **Sector**, **Industry Group**, and **Industry**.

---

## How It Works

```
zer0h/top-10000-domains          Two classification sources:
        (plain list)          +   1. Known-domain map (~500 major domains)
             |                    2. Cloudflare Radar API -> GICS mapper
             +-----------> enrich.py
                                 |
                     enriched_domains.csv
         rank | domain | gics_sector | gics_industry_group | industry | source
```

**Two-tier classification approach:**

1. **Known-Domain Map** — curated lookup of ~500 major domains with verified GICS industry data. Fastest, most accurate, no API needed. Covers nearly all top-100 domains.

2. **Cloudflare Radar Fallback** — for domains not in the curated map, fetches content categories from the free Cloudflare Radar API, then maps them to GICS industries via a conversion table (e.g., "Shopping/E-Commerce" → Consumer Discretionary / Retailing / Internet & Direct Marketing Retail).

---

## Sample Output

| rank | domain | gics_sector | gics_industry_group | industry | source |
|------|--------|-------------|---------------------|----------|--------|
| 1 | google.com | Technology | Software & Services | Internet Software & Services | known-domain-map |
| 2 | youtube.com | Communication Services | Media & Entertainment | Movies & Entertainment | known-domain-map |
| 3 | facebook.com | Communication Services | Media & Entertainment | Interactive Media & Services | known-domain-map |
| 6 | amazon.com | Consumer Discretionary | Retailing | Internet & Direct Marketing Retail | known-domain-map |
| 19 | bing.com | Technology | Software & Services | Internet Software & Services | known-domain-map |
| 28 | github.com | Technology | Software & Services | Application Software | known-domain-map |
| 32 | paypal.com | Financials | Diversified Financials | Transaction & Payment Processing Services | known-domain-map |
| 35 | bbc.com | Communication Services | Media & Entertainment | Broadcasting | known-domain-map |

See [sample_output.csv](./sample_output.csv) for the first 40 domains.

---

## Quick Start

### 1. Get a free Cloudflare API token (optional — only needed for unknown domains)

1. Go to [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click **Create Token** → custom token
3. Add permission: `Cloudflare Radar → Read`
4. Copy the token

### 2. Clone & run

```bash
git clone https://github.com/duplixx/domain-industry-enricher.git
cd domain-industry-enricher

# Option A: Fully offline (known-domain map only, no API key needed)
python enrich.py --limit 500 --offline

# Option B: Full enrichment (known map + Cloudflare fallback for unknowns)
export CF_API_TOKEN=your_token_here
python enrich.py --limit 1000

# Custom output file
python enrich.py --limit 500 --output my_results.csv
```

### 3. Analyze results

```bash
# Count by GICS sector
awk -F',' 'NR>1{print $3}' enriched_domains.csv | sort | uniq -c | sort -rn

# Count by industry
awk -F',' 'NR>1{print $5}' enriched_domains.csv | sort | uniq -c | sort -rn

# Filter by sector (e.g. Financials only)
awk -F',' '$3=="Financials"' enriched_domains.csv
```

---

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | 100 | Number of domains to process |
| `--output` | enriched_domains.csv | Output CSV file path |
| `--token` | (env var) | Cloudflare API token (or set `CF_API_TOKEN`) |
| `--delay` | 0.25 | Seconds between API calls |
| `--offline` | False | Use known-domain map only, skip all API calls |

---

## Output CSV Schema

```
rank,domain,gics_sector,gics_industry_group,industry,source
1,google.com,Technology,Software & Services,Internet Software & Services,known-domain-map
6,amazon.com,Consumer Discretionary,Retailing,Internet & Direct Marketing Retail,known-domain-map
32,paypal.com,Financials,Diversified Financials,Transaction & Payment Processing Services,known-domain-map
```

| Column | Description |
|--------|-------------|
| `rank` | Traffic rank (1 = most visited globally) |
| `domain` | Domain name |
| `gics_sector` | GICS Level 1 — e.g. Technology, Financials, Health Care |
| `gics_industry_group` | GICS Level 2 — e.g. Software & Services, Banks |
| `industry` | GICS Level 3 — e.g. Internet Software & Services, Diversified Banks |
| `source` | `known-domain-map` / `cf-radar-mapped` / `no-data` |

---

## GICS Sectors Covered

| GICS Sector | Example Domains |
|-------------|-----------------|
| Technology | google.com, microsoft.com, github.com, nvidia.com |
| Communication Services | youtube.com, facebook.com, twitter.com, netflix.com, bbc.com |
| Consumer Discretionary | amazon.com, booking.com, airbnb.com, ebay.com |
| Consumer Staples | walmart.com, costco.com |
| Financials | paypal.com, chase.com, stripe.com, coinbase.com |
| Health Care | webmd.com, pfizer.com, mayoclinic.org |
| Industrials | delta.com, uber.com, fedex.com |
| Energy | — |
| Real Estate | zillow.com, realtor.com |
| Government | irs.gov, usa.gov, nasa.gov |

---

## No Third-Party Dependencies

The core script uses **only Python standard library** (Python 3.8+). Zero pip installs needed for basic use. The optional `requirements.txt` adds pandas/tqdm/tabulate for convenience only.

---

## License

MIT — see [LICENSE](./LICENSE)
