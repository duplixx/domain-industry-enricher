# domain-industry-enricher

> **DIY tool to enrich a ranked top-domain list with industry/category data — free, using the Cloudflare Radar API.**

This project demonstrates how to take a plain list of top domains (like [zer0h/top-1000000-domains](https://github.com/zer0h/top-1000000-domains)) and automatically label each one with its industry category, producing an enriched CSV you can use for analytics, market research, or competitive intelligence.

---

## How It Works

```
zer0h/top-10000-domains          Cloudflare Radar API
        (plain list)          +   (free, domain categories)
             |                              |
             +-----------> enrich.py <------+
                                 |
                         enriched_domains.csv
                  rank | domain | category | subcategory
```

1. **Fetches** the ranked domain list directly from GitHub (no download needed)
2. **Queries** the Cloudflare Radar `/radar/domains/{domain}/categories` endpoint for each domain
3. **Writes** results incrementally to a CSV (so partial results are saved if interrupted)
4. **Prints** a live summary with a category breakdown at the end

---

## Sample Output

| rank | domain        | category                   | subcategory              |
|------|---------------|----------------------------|--------------------------|
| 1    | google.com    | Search Engines             |                          |
| 2    | youtube.com   | Streaming Media & Downloads| Video Streaming          |
| 3    | facebook.com  | Social Networking          | Social Media             |
| 6    | amazon.com    | Shopping                   | E-Commerce               |
| 7    | wikipedia.org | Reference & Research       | Online Encyclopedia      |
| 17   | linkedin.com  | Social Networking          | Professional Networking  |
| 28   | github.com    | Technology                 | Software Development     |
| 29   | stackoverflow.com | Technology             | Developer Resources      |

See [sample_output.csv](./sample_output.csv) for the first 30 domains.

---

## Quick Start

### 1. Get a free Cloudflare API token

1. Go to [dash.cloudflare.com/profile/api-tokens](https://dash.cloudflare.com/profile/api-tokens)
2. Click **Create Token** → use the **Read Analytics** template, or create a custom token
3. Under **Permissions**, add: `Cloudflare Radar → Read`
4. Copy the generated token

### 2. Clone & run

```bash
git clone https://github.com/duplixx/domain-industry-enricher.git
cd domain-industry-enricher

# Set your token
export CF_API_TOKEN=your_token_here

# Enrich the top 100 domains (fast, ~30 seconds)
python enrich.py --limit 100

# Enrich the top 1000 domains
python enrich.py --limit 1000

# Custom output file
python enrich.py --limit 500 --output my_results.csv
```

### 3. View results

```bash
# Quick peek
head -20 enriched_domains.csv

# Count by category (requires csvkit or awk)
awk -F',' 'NR>1{print $3}' enriched_domains.csv | sort | uniq -c | sort -rn
```

---

## CLI Options

| Flag | Default | Description |
|------|---------|-------------|
| `--limit` | 100 | Number of domains to process |
| `--output` | enriched_domains.csv | Output CSV file path |
| `--token` | (env var) | Cloudflare API token (or set `CF_API_TOKEN`) |
| `--delay` | 0.25 | Seconds between API calls (free tier: ~4 req/s) |

---

## Output CSV Schema

```
rank,domain,category,subcategory
1,google.com,Search Engines,
2,youtube.com,Streaming Media & Downloads,Video Streaming
...
```

| Column | Description |
|--------|-------------|
| `rank` | Traffic rank (1 = most visited) |
| `domain` | Domain name |
| `category` | Primary industry/content category from Cloudflare Radar |
| `subcategory` | Secondary category (if available) |

---

## Category Examples

Cloudflare Radar uses IAB-aligned content categories. Common ones you'll see:

- **Search Engines** — google.com, bing.com, baidu.com
- **Social Networking** — facebook.com, twitter.com, linkedin.com
- **Shopping / E-Commerce** — amazon.com, taobao.com, ebay.com
- **Streaming Media & Downloads** — youtube.com, netflix.com
- **News & Media** — cnn.com, bbc.com, nytimes.com
- **Technology** — github.com, stackoverflow.com, apple.com
- **Reference & Research** — wikipedia.org
- **Finance** — chase.com, paypal.com, bankofamerica.com
- **Health & Medicine** — webmd.com, mayo.clinic.com

---

## No Extra Dependencies

The core script uses **only Python standard library** (Python 3.8+). No pip installs required for basic use. Optional packages in `requirements.txt` add `pandas`, `tqdm`, and `tabulate` for convenience.

---

## Rate Limits & Cost

- The Cloudflare Radar API is **free** with an API token
- Free tier allows ~1200 requests/minute
- At the default 0.25s delay, processing 10,000 domains takes ~45 minutes
- Results are saved incrementally, so you can interrupt and resume

---

## Alternative Enrichment Sources

If Cloudflare Radar doesn't cover a domain, consider these alternatives:

| Source | Notes |
|--------|-------|
| [Curlie / DMOZ](https://curlie.org) | Open directory, bulk export available |
| [themains/piedomains](https://github.com/themains/piedomains) | ML classifier using homepage screenshots |
| SimilarWeb API | Commercial, very comprehensive |
| BuiltWith Trends | Tech stack + industry classification |

---

## License

MIT — see [LICENSE](./LICENSE)
