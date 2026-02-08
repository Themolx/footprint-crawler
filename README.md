# Footprint Crawler

**Czech Internet Tracking Observatory** — an automated Playwright-based crawler that maps the tracking ecosystem of Czech websites by intercepting network requests, classifying trackers, handling cookie consent banners, and measuring how consent choices affect tracking behavior.

Part of the [Footprint](https://github.com/Themolx/Incognito) research project at FAMU (Film and TV School of the Academy of Performing Arts in Prague).

## What It Does

1. **Visits 100 Czech websites** across 12 categories (news, e-commerce, government, finance, etc.)
2. **Intercepts all network requests** and classifies them against a tracker database (Google, Meta, Seznam.cz, Adform, etc.)
3. **Handles cookie consent** in 3 modes:
   - `ignore` — no interaction with consent banners
   - `accept` — clicks "Accept All" buttons
   - `reject` — clicks "Reject All" / "Only Necessary" buttons
4. **Dwells 60 seconds** after consent to capture cascading tracker activity
5. **Stores everything** in SQLite for analysis and visualization

## Key Findings (100 Czech Sites)

| Metric | Ignore | Accept | Reject |
|--------|--------|--------|--------|
| Avg 3rd-party requests | 79.3 | 88.3 (+11%) | 82.8 (+4%) |
| Avg tracking cookies | 2.7 | 4.4 (+63%) | 2.7 (0%) |
| Avg total cookies | 8.2 | 11.0 | 8.7 |

- **Google** tracks on 72/95 sites, **Seznam.cz** on 34, **Gemius** on 32
- Rejecting cookies barely reduces tracking vs. ignoring the banner
- 33% of banners successfully detected and interacted with

## Installation

```bash
# Clone
git clone https://github.com/Themolx/footprint-crawler.git
cd footprint-crawler

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install matplotlib  # for visualization

# Install Chromium for Playwright
playwright install chromium
```

## Quick Start

```bash
# Test with 3 sites in headed mode (visible browser)
python -m footprint_crawler --limit 3 --headed

# Full crawl (100 sites, 3 modes = 300 tasks)
python -m footprint_crawler

# Only ignore mode, 5 sites
python -m footprint_crawler --modes ignore --limit 5

# Resume a previous crawl (skip already-completed tasks)
python -m footprint_crawler --resume
```

## CLI Options

```
python -m footprint_crawler [OPTIONS]

  --config PATH      Path to config.yaml (default: ./config.yaml)
  --sites PATH       Override sites CSV file path
  --concurrency N    Number of concurrent browser contexts (default: 16)
  --modes MODES      Comma-separated consent modes (default: ignore,accept,reject)
  --limit N          Only crawl first N sites
  --headed           Run with visible browser windows
  --resume           Skip sites/modes already crawled successfully
  --no-color         Disable colored terminal output
  --verbose, -v      Enable DEBUG logging
```

## Visualization & Analysis

After a crawl, use `visualize.py` to generate charts and export data:

```bash
# Generate all charts + CSV exports + network graph + text report
python visualize.py --all

# Just print a text report to terminal
python visualize.py --report

# Only generate charts
python visualize.py

# Only export CSV files (for Excel/R/Pandas)
python visualize.py --export-csv

# Export network graph JSON (for D3.js)
python visualize.py --export-graph

# Custom output directory
python visualize.py --all --output-dir my_analysis/
```

### Generated Outputs

| Output | Description |
|--------|-------------|
| `consent_comparison.png` | Bar charts comparing 3rd-party requests, tracking cookies, and total cookies across consent modes |
| `top_trackers.png` | Top 20 tracker entities by site reach |
| `tracking_by_category.png` | Tracking intensity by website category (news, e-commerce, etc.) |
| `pre_post_consent.png` | Cookies set before vs. after consent (functional vs. tracking) |
| `cmp_distribution.png` | Pie chart of detected Consent Management Platforms |
| `top_tracked_sites.png` | 25 most-tracked Czech websites |
| `cookie_lifetimes.png` | Distribution of cookie lifetimes |
| `network_graph.json` | D3.js-compatible JSON for force-directed graph visualization |
| `csv/sessions.csv` | All crawl sessions with metrics |
| `csv/tracker_reach.csv` | Tracker entity reach across sites |
| `csv/cookies_summary.csv` | All captured cookies with metadata |

## Viewing the Database

The crawl data is stored in `data/footprint.db` (SQLite). You can explore it with:

```bash
# Command line
sqlite3 data/footprint.db

# Quick stats
sqlite3 data/footprint.db "SELECT consent_mode, COUNT(*), ROUND(AVG(third_party_requests),1) FROM crawl_sessions WHERE status='success' GROUP BY consent_mode;"

# Top trackers
sqlite3 data/footprint.db "SELECT tracker_entity, COUNT(DISTINCT session_id) FROM requests WHERE tracker_entity IS NOT NULL GROUP BY tracker_entity ORDER BY 2 DESC LIMIT 10;"
```

Or use a GUI tool like [DB Browser for SQLite](https://sqlitebrowser.org/) (free, cross-platform).

### Database Schema

- **`sites`** — 100 Czech websites with domain, category, rank
- **`crawl_sessions`** — one row per (site, consent_mode) crawl with aggregated metrics
- **`requests`** — every intercepted HTTP request with tracker classification
- **`cookies`** — every captured cookie with tracking classification and lifetime

## Project Structure

```
footprint-crawler/
  config.yaml                  # Crawler configuration
  requirements.txt             # Python dependencies
  visualize.py                 # Visualization & analysis tool
  footprint_crawler/
    __init__.py
    __main__.py                # Entry point
    cli.py                     # CLI args + orchestration + progress display
    config.py                  # Config dataclass + YAML loader
    models.py                  # Data models (CrawlResult, RequestRecord, etc.)
    db.py                      # SQLite schema + operations
    engine.py                  # Core Playwright crawl engine
    consent.py                 # Cookie consent detection (14 CMPs)
    tracker_db.py              # Tracker classification database
    utils.py                   # Domain extraction, hashing, URL utils
  data/
    sites/czech_top_100.csv    # Sites to crawl
    trackers/czech_trackers.json  # Czech-specific tracker definitions
```

## Configuration

Edit `config.yaml` to customize:

```yaml
crawler:
  concurrency: 16              # Parallel browser contexts
  page_timeout_ms: 45000       # Page load timeout
  post_consent_wait_ms: 60000  # Dwell time after consent (60s)
  final_dwell_ms: 15000        # Final wait after scrolling
  max_retries: 3               # Retries on failure
  headless: true               # Run without visible browser

browser:
  locale: "cs-CZ"              # Czech locale
  timezone: "Europe/Prague"
  geolocation:                  # Prague coordinates
    latitude: 50.0755
    longitude: 14.4378
```

## Consent Detection

The crawler detects and interacts with 14 Consent Management Platforms:

OneTrust, Cookiebot, CookieYes, Didomi, Quantcast, Termly, Osano, TrustArc, iubenda, Klaro, Complianz, Cookie Notice, Civic UK, Sourcepoint

Plus a multi-layered fallback system:
1. CMP-specific CSS selectors (main page + iframes)
2. Generic CSS-based banner detection
3. Context-aware text matching for Czech/English consent patterns
4. Nested iframe scanning

## Dependencies

- **[Playwright](https://playwright.dev/)** — browser automation
- **[aiosqlite](https://github.com/omnilib/aiosqlite)** — async SQLite
- **[PyYAML](https://pyyaml.org/)** — configuration
- **[tldextract](https://github.com/john-kurkowski/tldextract)** — domain parsing
- **[matplotlib](https://matplotlib.org/)** — chart generation (for `visualize.py`)

## License

Research project — FAMU, Prague.
