# Forebet Scraper

Automated scraping of forebet.com sports predictions via GitHub Actions.

## How it works

GitHub Actions runners have fresh Azure IPs each execution — they often pass Cloudflare blocks that hit datacenter IPs.

## Setup

1. Create a **private** GitHub repo
2. Push this repo with the `data/multi_sport_2026-03.csv` file
3. The workflow runs daily at 10:00 UTC, or trigger manually

## Manual trigger

Go to **Actions → Scrape Forebet Scores → Run workflow**

Options:
- **sport_filter**: Leave empty for all, or set to "Tennis", "Basketball", etc.
- **start_date** / **end_date**: Date range (default: 2026-03-01 to 2026-03-26)

## Output

After each run, download the artifact `scraped-scores-N` containing:
- `multi_sport_2026-03_with_scores.csv` — updated CSV with final scores
- `raw_scraped.json` — raw scraped data for debugging
- `unmatched.log` — matches that couldn't be matched to existing data
