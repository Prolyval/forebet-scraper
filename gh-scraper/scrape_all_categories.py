#!/usr/bin/env python3
"""
Forebet Multi-Category Scraper — FlareSolverr
Scrapes ALL football prediction categories from forebet.com:
  1X2, Over/Under 2.5, BTTS, Half-time, HT/FT, Double Chance,
  Asian Handicap, Corners, Cards, Goal Scorers

Usage:
  python scrape_all_categories.py              # today + tomorrow
  python scrape_all_categories.py --date 2026-03-30
  python scrape_all_categories.py --from 2026-03-01 --to 2026-03-31
  python scrape_all_categories.py --category 1X2  # single category
  START_DATE=2026-03-01 END_DATE=2026-03-31 python scrape_all_categories.py

Output: output/all_categories_YYYY-MM-DD.json + CSV
"""
import argparse
import csv
import json
import os
import re
import sys
import time
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

# ─── Configuration ────────────────────────────────────────────────────────────

FLARESOLVERR = os.environ.get("FLARESOLVERR_URL", "http://localhost:8191/v1")
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

CATEGORIES = {
    "1X2":              {"slug": "pronostics-1x2",              "type": "3way"},
    "O2.5":             {"slug": "moins-plus-2-5-de-buts",     "type": "2way"},
    "BTTS":             {"slug": "chaque-equipe-marque",       "type": "2way"},
    "HT":               {"slug": "mi-temps",                    "type": "3way"},
    "HT-FT":            {"slug": "mi-temps-fin",               "type": "multi"},
    "Double Chance":    {"slug": "chance-double",               "type": "3way"},
    "Handicap":         {"slug": "handicap-asiatique",          "type": "2way"},
    "Corners":          {"slug": "coins",                       "type": "2way"},
    "Cards":            {"slug": "cards",                       "type": "2way"},
    "Goal Scorers":     {"slug": "prévisions-buteurs",           "type": "scorers"},
}

# ─── FlareSolverr helpers ─────────────────────────────────────────────────────

def create_session():
    r = requests.post(FLARESOLVERR, json={"cmd": "sessions.create"}, timeout=15)
    d = r.json()
    if d.get("status") != "ok":
        raise Exception(f"Cannot create FlareSolverr session: {d}")
    sid = d["session"]
    print(f"📡 FlareSolverr session: {sid[:12]}...")
    return sid

def destroy_session(sid):
    try:
        requests.post(FLARESOLVERR, json={"cmd": "sessions.destroy", "session": sid}, timeout=5)
    except Exception:
        pass

def fetch_page(url, sid, max_timeout=120):
    """Fetch a page via FlareSolverr, returns HTML string or None."""
    for attempt in range(3):
        try:
            r = requests.post(FLARESOLVERR, json={
                "cmd": "request.get",
                "url": url,
                "maxTimeout": max_timeout * 1000,
                "session": sid,
            }, timeout=max_timeout + 15)
            d = r.json()
            if d.get("status") == "ok":
                html = d["solution"]["response"]
                if len(html) > 5000:
                    return html
                print(f"  ⚠️ Short response ({len(html)} chars), retry {attempt+1}/3")
            else:
                print(f"  ⚠️ FlareSolverr error: {d.get('message','?')}, retry {attempt+1}/3")
        except Exception as e:
            print(f"  ⚠️ Request error: {e}, retry {attempt+1}/3")
        time.sleep(5)
    return None

# ─── Parsing ──────────────────────────────────────────────────────────────────

def parse_odds(txt):
    """Parse odds text like '2.061.66' or '1.80 3.90 3.80' into list."""
    if not txt:
        return []
    txt = re.sub(r'[^\d.]', ' ', txt)
    odds = re.findall(r'\d+\.\d{2}', txt)
    return odds

def parse_match(rcnt, date_str, category, cat_info):
    """Parse a single match row from a category page."""
    m = {
        "date": date_str,
        "category": category,
        "cat_type": cat_info["type"],
    }
    try:
        # Teams
        tnms = rcnt.find("div", class_="tnms")
        if not tnms:
            return None
        home = tnms.find("span", class_="homeTeam")
        away = tnms.find("span", class_="awayTeam")
        dt = tnms.find("span", class_="date_bah")
        if not home or not away:
            return None
        m["home_team"] = home.get_text(strip=True)
        m["away_team"] = away.get_text(strip=True)
        m["match_time"] = dt.get_text(strip=True) if dt else ""

        # League
        stag = rcnt.find("span", class_="shortTag")
        if stag:
            m["league"] = stag.get_text(strip=True)

        # Match ID
        link = tnms.find("a", class_="tnmscn")
        if link:
            href = link.get("href", "")
            mid = re.search(r'/(\d+)$', href)
            if mid:
                m["match_id"] = mid.group(1)

        # Probabilities (fprc div)
        fprc = rcnt.find("div", class_="fprc")
        if fprc:
            spans = fprc.find_all("span")
            probs = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
            # Also check for playerPred divs (Goal Scorers)
            if not probs:
                pp_divs = fprc.find_all("div", class_="playerPred")
                probs = [d.get_text(strip=True) for d in pp_divs if d.get_text(strip=True)]
            if cat_info["type"] == "3way" and len(probs) >= 3:
                m["prob_1"], m["prob_2"], m["prob_3"] = probs[:3]
            elif cat_info["type"] == "2way" and len(probs) >= 2:
                m["prob_under"], m["prob_over"] = probs[:2]
            elif cat_info["type"] == "scorers" and probs:
                m["scorer_top_probs"] = probs
            elif cat_info["type"] == "multi" and len(probs) >= 2:
                m["probabilities"] = probs

        # Prediction (forepr) — also check frpr for Goal Scorers
        forepr = rcnt.find("span", class_="forepr")
        if not forepr:
            forepr = rcnt.find("span", class_="frpr")
        if forepr:
            m["prediction"] = forepr.get_text(strip=True)

        # For Goal Scorers: extract player names from playerPred divs
        if category == "Goal Scorers":
            pp_divs = rcnt.find_all("div", class_="playerPred")
            player_names = []
            player_probs = []
            for pp in pp_divs:
                txt = pp.get_text(strip=True)
                if not txt:
                    continue
                # Check if it's a probability (ends with %)
                if txt.endswith('%'):
                    player_probs.append(txt)
                else:
                    player_names.append(txt)
            if player_names:
                m["predicted_scorers"] = player_names
            if player_probs:
                m["scorer_probs"] = player_probs

        # Expected score (ex_sc)
        ex_sc = rcnt.find("div", class_="ex_sc")
        if ex_sc:
            txt = ex_sc.get_text(strip=True)
            if txt and txt != "-":
                m["predicted_value"] = txt

        # Average (avg_sc)
        avg_sc = rcnt.find("div", class_="avg_sc")
        if avg_sc:
            txt = avg_sc.get_text(strip=True)
            if txt and txt != "-":
                m["avg_value"] = txt

        # Odds (haodd)
        haodd = rcnt.find("div", class_="haodd")
        if haodd:
            odds = parse_odds(haodd.get_text())
            if len(odds) >= 2:
                m["odds"] = odds
            elif len(odds) == 1:
                m["odds"] = odds

        # Also check for visible odds in lscrsp (bigOnly prmod)
        prmod = rcnt.find("div", class_="prmod")
        if prmod and "odds" not in m:
            lscrsp = prmod.find("span", class_="lscrsp")
            if lscrsp:
                odds = parse_odds(lscrsp.get_text())
                if odds:
                    m["odds"] = odds

        # Score & status
        score_span = rcnt.find("b", class_="l_scr")
        if score_span:
            txt = score_span.get_text(strip=True)
            if txt:
                m["status"] = "FT"
                m["final_score"] = txt
            else:
                m["status"] = ""
        else:
            m["status"] = ""

        # Half-time score
        ht_scr = rcnt.find("span", class_="ht_scr")
        if ht_scr:
            m["ht_score"] = ht_scr.get_text(strip=True).strip("()")

        if m.get("home_team") and (m.get("prediction") or m.get("predicted_scorers")):
            return m

    except Exception as e:
        pass
    return None

# ─── Main scraper ─────────────────────────────────────────────────────────────

def scrape_category_date(sid, category, cat_info, date_str):
    """Scrape one category for one date."""
    slug = cat_info["slug"]
    if date_str:
        url = f"https://www.forebet.com/fr/pronostics-de-football/{slug}/{date_str}"
    else:
        url = f"https://www.forebet.com/fr/pronostics-de-football/{slug}"

    print(f"  🌐 {url}")
    html = fetch_page(url, sid)
    if not html:
        print(f"  ❌ Failed to fetch")
        return []

    soup = BeautifulSoup(html, "html.parser")
    rcnts = soup.find_all("div", class_="rcnt")

    matches = []
    for rcnt in rcnts:
        m = parse_match(rcnt, date_str or datetime.now().strftime("%Y-%m-%d"), category, cat_info)
        if m:
            matches.append(m)

    print(f"  ✅ {len(matches)} matches parsed")
    return matches


def main():
    parser = argparse.ArgumentParser(description="Forebet Multi-Category Scraper")
    parser.add_argument("--date", help="Single date YYYY-MM-DD")
    parser.add_argument("--from", dest="from_date", help="Start date YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="End date YYYY-MM-DD")
    parser.add_argument("--category", help="Single category (default: all)")
    parser.add_argument("--flaresolverr", default=FLARESOLVERR, help="FlareSolverr URL")
    args = parser.parse_args()

    flaresolverr_url = args.flaresolverr

    # Determine date range
    if args.date:
        dates = [args.date]
    elif args.from_date or args.to_date:
        start = datetime.strptime(args.from_date or datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d")
        end = datetime.strptime(args.to_date or datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d")
        dates = []
        d = start
        while d <= end:
            dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)
    else:
        # Default: today + tomorrow
        dates = [(datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(2)]

    # Determine categories
    if args.category:
        if args.category not in CATEGORIES:
            print(f"❌ Unknown category '{args.category}'. Available: {list(CATEGORIES.keys())}")
            sys.exit(1)
        cats = {args.category: CATEGORIES[args.category]}
    else:
        cats = CATEGORIES

    print(f"📊 Forebet Multi-Category Scraper")
    print(f"   Dates: {dates[0]} → {dates[-1]} ({len(dates)} days)")
    print(f"   Categories: {list(cats.keys())}")
    print(f"   Total pages: {len(dates) * len(cats)}")

    sid = create_session()

    # Warm up session on homepage
    print("\n🔄 Warming up session...")
    fetch_page("https://www.forebet.com/fr/", sid)
    time.sleep(3)

    all_matches = []
    total_pages = len(dates) * len(cats)
    page_num = 0

    for cat_name, cat_info in cats.items():
        for date_str in dates:
            page_num += 1
            print(f"\n[{page_num}/{total_pages}] {cat_name} — {date_str}")
            matches = scrape_category_date(sid, cat_name, cat_info, date_str)
            all_matches.extend(matches)

            # Rate limit: 4-6s between pages
            if page_num < total_pages:
                time.sleep(4 + (page_num % 3) * 2)

            # Refresh session every 15 pages to avoid staleness
            if page_num % 15 == 0 and page_num < total_pages:
                print("  🔄 Refreshing session...")
                fetch_page("https://www.forebet.com/fr/", sid)
                time.sleep(3)

    destroy_session(sid)

    # ─── Save results ─────────────────────────────────────────────────────

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # JSON
    json_path = OUTPUT_DIR / f"all_categories_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_matches, f, ensure_ascii=False, indent=2)
    print(f"\n💾 JSON: {json_path}")

    # CSV
    if all_matches:
        # Flatten nested fields for CSV
        flat = []
        for m in all_matches:
            row = {}
            for k, v in m.items():
                if isinstance(v, list):
                    row[k] = " | ".join(str(x) for x in v)
                else:
                    row[k] = v
            flat.append(row)

        csv_path = OUTPUT_DIR / f"all_categories_{ts}.csv"
        fieldnames = []
        for m in flat:
            for k in m.keys():
                if k not in fieldnames:
                    fieldnames.append(k)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(flat)
        print(f"💾 CSV: {csv_path}")

    # Summary
    by_cat = {}
    for m in all_matches:
        by_cat[m["category"]] = by_cat.get(m["category"], 0) + 1

    print(f"\n{'='*50}")
    print(f"📊 Total: {len(all_matches)} predictions")
    for cat, count in sorted(by_cat.items()):
        print(f"   {cat:15s}: {count}")
    print(f"{'='*50}")

    return all_matches


if __name__ == "__main__":
    main()
