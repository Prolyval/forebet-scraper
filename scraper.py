#!/usr/bin/env python3
"""
Forebet Historical Scraper - v4 (1X2 only, optimized)
Scrapes 2026-03-01 to 2026-03-26 via FlareSolverr.
"""

import json, time, re, os, requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd

FLARESOLVERR = "http://localhost:8191/v1"
OUTPUT_DIR = "/root/.openclaw/workspace/forebet/data"

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

def parse_rcnt(rcnt, date_str):
    m = {"date": date_str}

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

    fprc = rcnt.find("div", class_="fprc")
    if fprc:
        spans = fprc.find_all("span")
        if len(spans) >= 3:
            m["prob_1"] = int(spans[0].get_text(strip=True))
            m["prob_x"] = int(spans[1].get_text(strip=True))
            m["prob_2"] = int(spans[2].get_text(strip=True))

    pred_div = rcnt.find("div", class_="predict_y") or rcnt.find("div", class_="predict_no")
    if pred_div:
        fp = pred_div.find("span", class_="forepr")
        if fp:
            m["prediction"] = fp.get_text(strip=True)
        sp = pred_div.find("span", class_="scrmobpred")
        if sp:
            m["predicted_score"] = sp.get_text(strip=True)

    avg = rcnt.find("div", class_="avg_sc")
    if avg:
        m["avg_goals"] = avg.get_text(strip=True)

    wth = rcnt.find("div", class_="prwth")
    if wth:
        wn = wth.find("span", class_="wnums")
        if wn:
            m["weather"] = wn.get_text(strip=True)

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
                m["odds_1"] = nums[0]
                m["odds_x"] = nums[1]
                m["odds_2"] = nums[2]

    lmin = rcnt.find("div", class_="lmin_td")
    if lmin:
        m["status"] = lmin.get_text(strip=True)

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
                m["ht_home_goals"] = int(htsc.group(1))
                m["ht_away_goals"] = int(htsc.group(2))

    return m

def scrape_date(date_str):
    url = f"https://www.forebet.com/fr/pronostics-de-football/pronostics-1x2/{date_str}"
    print(f"  {date_str}: ", end="", flush=True)
    html = fetch_page(url)
    if not html:
        print("FAILED")
        return []

    soup = BeautifulSoup(html, "html.parser")
    matches = []

    for schema in soup.find_all("div", class_="schema"):
        # Try to find league name before schema
        league = ""
        # Check preceding elements
        prev_el = schema.find_previous_sibling()
        while prev_el:
            if prev_el.name in ['h2', 'h3', 'div']:
                t = prev_el.get_text(strip=True)
                if t and len(t) < 100:
                    league = t
                    break
            prev_el = prev_el.find_previous_sibling()

        for rcnt in schema.find_all("div", class_="rcnt"):
            m = parse_rcnt(rcnt, date_str)
            if m:
                m["league"] = league
                matches.append(m)

    print(f"{len(matches)} matches")
    return matches

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    start = datetime(2026, 3, 1)
    end = datetime(2026, 3, 26)
    all_matches = []
    current = start

    print(f"Scraping {((end - start).days + 1)} days of Forebet 1X2 data...\n")

    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        matches = scrape_date(ds)
        all_matches.extend(matches)
        time.sleep(3)
        current += timedelta(days=1)

    if all_matches:
        df = pd.DataFrame(all_matches)
        csv_path = f"{OUTPUT_DIR}/historical_2026-03.csv"
        df.to_csv(csv_path, index=False)

        print(f"\n{'='*50}")
        print(f"✅ {len(df)} matches saved to {csv_path}")
        print(f"   Dates: {df['date'].nunique()}")
        print(f"   With final score: {df['final_score'].notna().sum()}")
        print(f"   With odds: {df['odds_1'].notna().sum()}")
        print(f"   With probabilities: {df['prob_1'].notna().sum()}")

        # Prediction accuracy
        scored = df.dropna(subset=['prediction', 'home_goals', 'away_goals'])
        if len(scored) > 0:
            correct = 0
            for _, r in scored.iterrows():
                p, hg, ag = r['prediction'], r['home_goals'], r['away_goals']
                if p == '1' and hg > ag: correct += 1
                elif p == 'X' and hg == ag: correct += 1
                elif p == '2' and hg < ag: correct += 1
            print(f"   Forebet prediction accuracy: {correct}/{len(scored)} = {correct/len(scored)*100:.1f}%")

        # League breakdown
        print(f"\n   Top leagues:")
        for lg in df['league_code'].value_counts().head(10).index:
            n = df[df['league_code'] == lg].shape[0]
            print(f"     {lg}: {n} matches")
    else:
        print("\n❌ No matches found!")

if __name__ == "__main__":
    main()
