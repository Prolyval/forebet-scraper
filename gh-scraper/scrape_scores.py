#!/usr/bin/env python3
"""Scrape final scores from forebet for non-football sports.
Run via GitHub Actions to bypass Cloudflare IP blocks.
"""
import csv
import json
import os
import re
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4", "-q"])
    import requests
    from bs4 import BeautifulSoup

SPORT_SLUGS = {
    "Tennis": "tennis",
    "Basketball": "basketball",
    "Hockey": "hockey",
    "Volleyball": "volleyball",
    "Handball": "handball",
    "Cricket": "cricket",
    "Baseball": "baseball",
    "Rugby": "rugby",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def parse_score(score_text, sport):
    """Parse score text like '2 - 0(0 - 0)' into home_goals, away_goals.
    For tennis sets like '2-0 6-4 7-5', store sets won."""
    if not score_text:
        return None, None, None
    
    score_text = score_text.strip()
    
    if sport == "Tennis":
        # Tennis: "2-0 6-4 7-5" → sets: 2-0, or "2 - 0(0 - 0)" format
        m = re.match(r'(\d+)\s*[-–]\s*(\d+)', score_text)
        if m:
            return int(m.group(1)), int(m.group(2)), score_text
        return None, None, score_text
    
    # Football-style scores: "2 - 0(0 - 0)" or "2 - 0"
    m = re.match(r'(\d+)\s*[-–]\s*(\d+)', score_text)
    if m:
        return int(m.group(1)), int(m.group(2)), score_text
    
    return None, None, score_text


def scrape_date_sport(date_str, sport_slug, session):
    """Scrape one page and extract scores."""
    url = f"https://www.forebet.com/fr/{sport_slug}/predictions/{date_str}"
    
    try:
        resp = session.get(url, headers=HEADERS, timeout=30)
        
        if resp.status_code == 403:
            print(f"  ❌ 403 BLOCKED: {url}")
            return None
        if resp.status_code != 200:
            print(f"  ⚠️ HTTP {resp.status_code}: {url}")
            return None
        
        soup = BeautifulSoup(resp.text, "html.parser")
        rows = soup.select(".tr_0")
        
        if not rows:
            # Check if it's a Cloudflare challenge page
            if "just a moment" in resp.text.lower() or "cloudflare" in resp.text.lower():
                print(f"  ❌ Cloudflare challenge: {url}")
                return None
            print(f"  ℹ️ No matches found: {url}")
            return []
        
        results = []
        for row in rows:
            # Teams
            teams_el = row.select_one(".tnms")
            if not teams_el:
                continue
            teams_text = teams_el.get_text(strip=True)
            
            # Score - try multiple selectors
            score_el = row.select_one(".lscr_td")
            if not score_el:
                continue
            score_text = score_el.get_text(strip=True)
            
            if not score_text or score_text in ["-", "–", ""]:
                continue
            
            # Status
            status_el = row.select_one(".lmin_td")
            status = status_el.get_text(strip=True) if status_el else "FT"
            
            # Split teams (tricky: concatenated without separator)
            # We'll use the match from existing CSV if possible
            results.append({
                "teams_text": teams_text,
                "score_text": score_text,
                "status": status,
            })
        
        print(f"  ✅ {len(results)} scored matches: {url}")
        return results
        
    except Exception as e:
        print(f"  ❌ Error: {url} → {e}")
        return None


def load_existing_csv():
    """Load existing multi_sport CSV to get match identifiers."""
    csv_path = Path(__file__).parent / "multi_sport_2026-03.csv"
    if not csv_path.exists():
        print("⚠️ No existing CSV found at", csv_path)
        return []
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        matches = list(reader)
    
    print(f"Loaded {len(matches)} existing matches from CSV")
    return matches


def match_teams(scraped_teams, existing_home, existing_away):
    """Check if scraped team text matches an existing match."""
    # The scraped text has concatenated team names without separator
    # e.g., "Player APlayer B" for tennis or "Team ATeam B" for basketball
    home_in = existing_home.lower().replace(" ", "") in scraped_teams.lower().replace(" ", "")
    away_in = existing_away.lower().replace(" ", "") in scraped_teams.lower().replace(" ", "")
    return home_in and away_in


def main():
    # Configuration
    start_date = os.environ.get("START_DATE", "2026-03-01")
    end_date = os.environ.get("END_DATE", "2026-03-26")
    sport_filter = os.environ.get("SPORT_FILTER", "")  # empty = all
    
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Load existing matches
    existing = load_existing_csv()
    if not existing:
        print("Nothing to do - no existing matches")
        return
    
    # Build lookup: (date, sport) → list of matches
    by_date_sport = {}
    for m in existing:
        key = (m["date"], m["sport"])
        by_date_sport.setdefault(key, []).append(m)
    
    # Build scrape plan
    plan = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        for sport_name, sport_slug in SPORT_SLUGS.items():
            if sport_filter and sport_name != sport_filter:
                continue
            if (date_str, sport_name) in by_date_sport:
                plan.append((date_str, sport_name, sport_slug))
        current += timedelta(days=1)
    
    print(f"\n📊 Scrape plan: {len(plan)} pages to fetch")
    print(f"   Dates: {start_date} to {end_date}")
    print(f"   Sports: {list(SPORT_SLUGS.keys())}")
    
    # Scrape
    session = requests.Session()
    session.headers.update(HEADERS)
    
    all_results = {}  # (date, sport) → list of scraped results
    blocked = 0
    success = 0
    
    for i, (date_str, sport_name, sport_slug) in enumerate(plan):
        print(f"\n[{i+1}/{len(plan)}] {date_str} - {sport_name}")
        
        # Hit homepage first every 10 requests to refresh cookies
        if i > 0 and i % 10 == 0:
            try:
                session.get("https://www.forebet.com/fr/", timeout=15)
                time.sleep(2)
            except:
                pass
        
        results = scrape_date_sport(date_str, sport_slug, session)
        
        if results is None:
            blocked += 1
            if blocked >= 3:
                print("\n🛑 Too many blocks, stopping to avoid permanent ban")
                break
            time.sleep(5)
        else:
            blocked = 0
            success += 1
            all_results[(date_str, sport_name)] = results
        
        # Rate limit: 3-5s between requests
        time.sleep(3 + (i % 3) * 1.5)
    
    print(f"\n{'='*50}")
    print(f"Results: {success} scraped, {blocked} blocked")
    
    # Match scores to existing CSV
    updated_matches = []
    matched = 0
    unmatched_scores = []
    
    for m in existing:
        key = (m["date"], m["sport"])
        if key in all_results:
            scraped = all_results[key]
            found = False
            for s in scraped:
                if match_teams(s["teams_text"], m["home_team"], m["away_team"]):
                    m["final_score"] = s["score_text"]
                    m["status"] = s["status"]
                    matched += 1
                    found = True
                    break
            if not found:
                # Store unmatched for debugging
                unmatched_scores.append(f"{key}: no match for {m['home_team']} vs {m['away_team']}")
        updated_matches.append(m)
    
    print(f"✅ Matched {matched} scores to existing matches")
    if unmatched_scores:
        print(f"⚠️ {len(unmatched_scores)} unmatched (saved to unmatched.log)")
        with open(OUTPUT_DIR / "unmatched.log", "w") as f:
            f.write("\n".join(unmatched_scores))
    
    # Save updated CSV
    if updated_matches:
        out_path = OUTPUT_DIR / "multi_sport_2026-03_with_scores.csv"
        fieldnames = list(updated_matches[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(updated_matches)
        print(f"💾 Saved to {out_path}")
    
    # Also save raw scraped data for debugging
    raw_path = OUTPUT_DIR / "raw_scraped.json"
    raw = {f"{k[0]}_{k[1]}": v for k, v in all_results.items()}
    with open(raw_path, "w") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)
    
    # Summary
    scored = sum(1 for m in updated_matches if m.get("final_score") and m["final_score"] not in ["", "-", "–"])
    print(f"\n📈 Total with scores: {scored}/{len(updated_matches)}")
    
    return scored


if __name__ == "__main__":
    main()
