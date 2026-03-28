#!/usr/bin/env python3
"""Multi-sport scraper for Forebet - 01/03 to 26/03/2026"""

import json, time, re, os, requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd

FLARESOLVERR = "http://localhost:8191/v1"
OUTPUT_DIR = "/root/.openclaw/workspace/forebet/data"

SPORTS = [
    ("tennis", "Tennis", "tennis"),
    ("basketball", "Basketball", "basketball"),
    ("hockey", "Hockey", "hockey"),
    ("volleyball", "Volleyball", "volleyball"),
    ("handball", "Handball", "handball"),
    ("cricket", "Cricket", "cricket"),
    ("baseball", "Baseball", "baseball"),
    ("rugby", "Rugby", "rugby"),
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

def parse_rcnt(rcnt, date_str, sport):
    m = {"date": date_str, "sport": sport}

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
        if len(spans) >= 2:
            m["prob_a"] = int(spans[0].get_text(strip=True))
            m["prob_b"] = int(spans[1].get_text(strip=True))
            if len(spans) >= 3:
                m["prob_c"] = int(spans[2].get_text(strip=True))

    pred_div = rcnt.find("div", class_="predict_y") or rcnt.find("div", class_="predict_no")
    if pred_div:
        fp = pred_div.find("span", class_="forepr")
        if fp:
            m["prediction"] = fp.get_text(strip=True)
        sp = pred_div.find("span", class_="scrmobpred")
        if sp:
            m["predicted_value"] = sp.get_text(strip=True)

    avg = rcnt.find("div", class_="avg_sc")
    if avg:
        m["avg_value"] = avg.get_text(strip=True)

    prmod = rcnt.find("div", class_="prmod")
    if prmod:
        haodd = prmod.find("div", class_="haodd")
        if haodd:
            spans = haodd.find_all("span")
            nums = []
            for sp in spans:
                t = sp.get_text(strip=True)
                try: nums.append(float(t))
                except: nums.append(None)
            if len(nums) >= 3:
                m["odds_a"] = nums[0]; m["odds_b"] = nums[1]; m["odds_c"] = nums[2]

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
                m["ht_home"] = int(htsc.group(1)); m["ht_away"] = int(htsc.group(2))

    return m

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    start = datetime(2026, 3, 1)
    end = datetime(2026, 3, 26)
    all_matches = []
    current = start
    total = len(SPORTS) * 26
    req_n = 0

    print(f"Scraping {len(SPORTS)} sports × 26 days = {total} requests\n")

    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        print(f"📅 {ds}")
        for _, name, slug in SPORTS:
            req_n += 1
            url = f"https://www.forebet.com/fr/{slug}/predictions/{ds}"
            html = fetch_page(url)
            n = 0
            if html:
                soup = BeautifulSoup(html, "html.parser")
                for schema in soup.find_all("div", class_="schema"):
                    for rcnt in schema.find_all("div", class_="rcnt"):
                        m = parse_rcnt(rcnt, ds, name)
                        if m:
                            all_matches.append(m)
                            n += 1
            print(f"  [{req_n}/{total}] {name:15s} -> {n:4d} matchs")
            time.sleep(3)
        current += timedelta(days=1)

    if all_matches:
        df = pd.DataFrame(all_matches)
        csv_path = f"{OUTPUT_DIR}/multi_sport_2026-03.csv"
        df.to_csv(csv_path, index=False)
        print(f"\n{'='*50}")
        print(f"✅ {len(df)} total rows saved")
        for _, name, _ in SPORTS:
            n = len(df[df['sport']==name])
            print(f"   {name:15s} : {n:6d} rows")
    else:
        print("\n❌ No matches!")

if __name__ == "__main__":
    main()
