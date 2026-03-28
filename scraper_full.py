#!/usr/bin/env python3
"""
Forebet Full Historical Scraper - v5
All categories, 2026-03-01 to 2026-03-26
"""

import json, time, re, os, requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd

FLARESOLVERR = "http://localhost:8191/v1"
OUTPUT_DIR = "/root/.openclaw/workspace/forebet/data"

CATEGORIES = [
    ("pronostics-1x2", "1X2"),
    ("moins-plus-2-5-de-buts", "Over/Under 2.5"),
    ("mi-temps", "Mi-temps"),
    ("mi-temps-fin", "HT/FT"),
    ("chaque-equipe-marque", "BTTS"),
    ("chance-double", "Double Chance"),
    ("handicap-asiatique", "Handicap"),
    ("coins", "Corners"),
    ("cards", "Cartons"),
]

def fetch_page(url):
    try:
        r = requests.post(FLARESOLVERR, json={
            "cmd": "request.get", "url": url, "maxTimeout": 60000
        }, timeout=120)
        d = r.json()
        if d.get("status") == "ok":
            return d["solution"]["response"]
        return None
    except:
        return None

def parse_rcnt(rcnt, date_str, category):
    m = {"date": date_str, "category": category}

    stcn = rcnt.find("div", class_="stcn")
    if stcn:
        s = stcn.find("div", class_="shortagDiv")
        m["league_code"] = (s or stcn).get_text(strip=True)

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
    m["match_datetime"] = dt.get_text(strip=True) if dt else ""

    # Probabilities
    fprc = rcnt.find("div", class_="fprc")
    if fprc:
        spans = fprc.find_all("span")
        if len(spans) >= 2:
            m["prob_a"] = int(spans[0].get_text(strip=True))
            m["prob_b"] = int(spans[1].get_text(strip=True))
            if len(spans) >= 3:
                m["prob_c"] = int(spans[2].get_text(strip=True))

    # Prediction
    pred_div = rcnt.find("div", class_="predict_y") or rcnt.find("div", class_="predict_no")
    if pred_div:
        fp = pred_div.find("span", class_="forepr")
        if fp:
            m["prediction"] = fp.get_text(strip=True)
        sp = pred_div.find("span", class_="scrmobpred")
        if sp:
            m["predicted_value"] = sp.get_text(strip=True)

    # Avg score
    avg = rcnt.find("div", class_="avg_sc")
    if avg:
        m["avg_value"] = avg.get_text(strip=True)

    # Weather
    wth = rcnt.find("div", class_="prwth")
    if wth:
        wn = wth.find("span", class_="wnums")
        if wn:
            m["weather"] = wn.get_text(strip=True)

    # Odds
    prmod = rcnt.find("div", class_="prmod")
    if prmod:
        haodd = prmod.find("div", class_="haodd")
        if haodd:
            spans = haodd.find_all("span")
            nums = []
            for sp in spans:
                t = sp.get_text(strip=True)
                try:
                    nums.append(float(t))
                except ValueError:
                    nums.append(None)
            if len(nums) >= 3:
                m["odds_a"] = nums[0]
                m["odds_b"] = nums[1]
                m["odds_c"] = nums[2]

    # Status
    lmin = rcnt.find("div", class_="lmin_td")
    if lmin:
        m["status"] = lmin.get_text(strip=True)

    # Final score
    lscr = rcnt.find("div", class_="lscr_td")
    if lscr:
        sp = lscr.find("span", class_="lscrsp")
        if sp:
            m["final_score"] = sp.get_text(strip=True)
            sc = re.match(r'(\d+)\s*-\s*(\d+)', sp.get_text(strip=True))
            if sc:
                m["home_goals"] = int(sc.group(1))
                m["away_goals"] = int(sc.group(2))
        ht = lscr.find("span", class_="ht_scr")
        if ht:
            m["ht_score"] = ht.get_text(strip=True)
            htsc = re.search(r'\((\d+)\s*-\s*(\d+)\)', ht.get_text())
            if htsc:
                m["ht_home"] = int(htsc.group(1))
                m["ht_away"] = int(htsc.group(2))

    return m

def scrape_date_category(date_str, slug, cat_name):
    url = f"https://www.forebet.com/fr/pronostics-de-football/{slug}/{date_str}"
    html = fetch_page(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    matches = []

    for schema in soup.find_all("div", class_="schema"):
        for rcnt in schema.find_all("div", class_="rcnt"):
            m = parse_rcnt(rcnt, date_str, cat_name)
            if m:
                matches.append(m)

    return matches

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    start = datetime(2026, 3, 1)
    end = datetime(2026, 3, 26)
    all_matches = []
    current = start
    total_req = len(CATEGORIES) * ((end - start).days + 1)
    req_n = 0

    print(f"Scraping {len(CATEGORIES)} categories × 26 days = {total_req} requests\n")

    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        print(f"📅 {ds}")
        for slug, name in CATEGORIES:
            req_n += 1
            matches = scrape_date_category(ds, slug, name)
            all_matches.extend(matches)
            print(f"  [{req_n}/{total_req}] {name:25s} -> {len(matches)} matchs")
            time.sleep(3)
        current += timedelta(days=1)

    if all_matches:
        df = pd.DataFrame(all_matches)
        csv_path = f"{OUTPUT_DIR}/full_historical_2026-03.csv"
        df.to_csv(csv_path, index=False)

        print(f"\n{'='*50}")
        print(f"✅ {len(df)} total rows saved")
        for cat in CATEGORIES:
            n = len(df[df['category']==cat[1]])
            print(f"   {cat[1]:25s} : {n} rows")
    else:
        print("\n❌ No matches!")

if __name__ == "__main__":
    main()
