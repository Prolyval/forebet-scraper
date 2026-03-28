#!/usr/bin/env python3
"""
Forebet MEGA Scraper - Fixed score extraction for ALL sports and categories
"""
import json, time, re, os, requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pandas as pd

FLARESOLVERR = "http://localhost:8191/v1"
OUTPUT_DIR = "/root/.openclaw/workspace/forebet/data"

FOOTBALL_CATS = [
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

OTHER_SPORTS = [
    ("tennis", "Tennis"),
    ("basketball", "Basketball"),
    ("hockey", "Hockey"),
    ("volleyball", "Volleyball"),
    ("handball", "Handball"),
    ("cricket", "Cricket"),
    ("baseball", "Baseball"),
    ("rugby", "Rugby"),
]

def fetch_page(url):
    try:
        r = requests.post(FLARESOLVERR, json={"cmd":"request.get","url":url,"maxTimeout":60000}, timeout=120)
        d = r.json()
        if d.get("status") == "ok": return d["solution"]["response"]
        return None
    except: return None

def parse_score(rcnt, predicted_value):
    """Parse actual score using predicted score length as guide"""
    if not predicted_value: return None, None, None, None
    
    pred_clean = predicted_value.replace(' ','')
    parts = pred_clean.split('-')
    if len(parts) != 2: return None, None, None, None
    
    try:
        pred_h, pred_a = float(parts[0]), float(parts[1])
    except: return None, None, None, None
    
    pred_lens = (len(parts[0]), len(parts[1]))
    
    lscr = rcnt.find("div", class_="lscr_td")
    if not lscr: return None, None, None, None
    
    fj = lscr.find("div", class_="fj_column")
    if not fj:
        # Try standard score parsing with separator
        sp = lscr.find("span", class_="lscrsp")
        if sp:
            txt = sp.get_text(strip=True)
            m = re.match(r'(\d+)\s*[-:]\s*(\d+)', txt)
            if m:
                return int(m.group(1)), int(m.group(2)), pred_h, pred_a
        return None, None, None, None
    
    fj_text = fj.get_text(strip=True).replace(' ','')
    if len(fj_text) != sum(pred_lens): return None, None, None, None
    
    actual_h = float(fj_text[:pred_lens[0]])
    actual_a = float(fj_text[pred_lens[0]:])
    return actual_h, actual_a, pred_h, pred_a

def parse_rcnt(rcnt, date_str, sport, category):
    m = {"date": date_str, "sport": sport, "category": category}
    
    stcn = rcnt.find("div", class_="stcn")
    if stcn:
        s = stcn.find("div", class_="shortagDiv")
        m["league_code"] = (s or stcn).get_text(strip=True)
    
    tnms = rcnt.find("div", class_="tnms")
    if not tnms: return None
    home = tnms.find("span", class_="homeTeam")
    away = tnms.find("span", class_="awayTeam")
    dt = tnms.find("span", class_="date_bah")
    if not home or not away: return None
    m["home_team"] = home.get_text(strip=True)
    m["away_team"] = away.get_text(strip=True)
    m["match_datetime"] = dt.get_text(strip=True) if dt else ""
    
    # Probabilities
    fprc = rcnt.find("div", class_="fprc")
    if fprc:
        spans = fprc.find_all("span")
        if len(spans) >= 2:
            m["prob_a"] = spans[0].get_text(strip=True)
            m["prob_b"] = spans[1].get_text(strip=True)
            if len(spans) >= 3: m["prob_c"] = spans[2].get_text(strip=True)
    
    # Prediction
    pred_div = rcnt.find("div", class_="predict_y") or rcnt.find("div", class_="predict_no")
    if pred_div:
        fp = pred_div.find("span", class_="forepr")
        if fp: m["prediction"] = fp.get_text(strip=True)
        sp = pred_div.find("span", class_="scrmobpred")
        if sp: m["predicted_value"] = sp.get_text(strip=True)
    
    # Avg value
    avg = rcnt.find("div", class_="avg_sc")
    if avg: m["avg_value"] = avg.get_text(strip=True)
    
    # Odds
    prmod = rcnt.find("div", class_="prmod")
    if prmod:
        haodd = prmod.find("div", class_="haodd")
        if haodd:
            nums = []
            for sp in haodd.find_all("span"):
                try: nums.append(float(sp.get_text(strip=True)))
                except: nums.append(None)
            if len(nums) >= 3:
                m["odds_a"], m["odds_b"], m["odds_c"] = nums[0], nums[1], nums[2]
    
    # Status
    lmin = rcnt.find("div", class_="lmin_td")
    if lmin: m["status"] = lmin.get_text(strip=True)
    
    # SCORE - fixed parsing
    pred_val = m.get("predicted_value")
    actual_h, actual_a, pred_h, pred_a = parse_score(rcnt, pred_val)
    
    if actual_h is not None:
        m["home_score"] = int(actual_h)
        m["away_score"] = int(actual_a)
        m["pred_home"] = int(pred_h)
        m["pred_away"] = int(pred_a)
        m["score_diff"] = round((actual_h + actual_a) - (pred_h + pred_a), 1)
        m["home_diff"] = round(actual_h - pred_h, 1)
        m["away_diff"] = round(actual_a - pred_a, 1)
    
    # HT score for football
    lscr = rcnt.find("div", class_="lscr_td")
    if lscr:
        ht = lscr.find("span", class_="ht_scr")
        if ht:
            htsc = re.search(r'\((\d+)\s*-\s*(\d+)\)', ht.get_text())
            if htsc:
                m["ht_home"] = int(htsc.group(1))
                m["ht_away"] = int(htsc.group(2))
    
    return m

def scrape_url(url, date_str, sport, category):
    html = fetch_page(url)
    if not html: return []
    soup = BeautifulSoup(html, "html.parser")
    matches = []
    for schema in soup.find_all("div", class_="schema"):
        for rcnt in schema.find_all("div", class_="rcnt"):
            m = parse_rcnt(rcnt, date_str, sport, category)
            if m: matches.append(m)
    return matches

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    start = datetime(2026, 3, 1)
    end = datetime(2026, 3, 26)
    all_matches = []
    
    # Count total requests
    fb_total = len(FOOTBALL_CATS) * 26
    other_total = len(OTHER_SPORTS) * 26
    total = fb_total + other_total
    req_n = 0
    
    print(f"MEGA SCRAPE: {total} requests ({fb_total} football + {other_total} other sports)")
    print()
    
    current = start
    while current <= end:
        ds = current.strftime("%Y-%m-%d")
        print(f"📅 {ds}")
        
        # Football categories
        for slug, cat_name in FOOTBALL_CATS:
            req_n += 1
            url = f"https://www.forebet.com/fr/pronostics-de-football/{slug}/{ds}"
            matches = scrape_url(url, ds, "Football", cat_name)
            all_matches.extend(matches)
            print(f"  [{req_n}/{total}] ⚽ {cat_name:20s} -> {len(matches):4d} ({sum(1 for m in matches if 'home_score' in m)} scored)")
            time.sleep(3)
        
        # Other sports
        for slug, sport in OTHER_SPORTS:
            req_n += 1
            url = f"https://www.forebet.com/fr/{slug}/predictions/{ds}"
            matches = scrape_url(url, ds, sport, sport)
            all_matches.extend(matches)
            scored = sum(1 for m in matches if 'home_score' in m)
            print(f"  [{req_n}/{total}] {sport:12s} -> {len(matches):4d} ({scored} scored)")
            time.sleep(3)
        
        current += timedelta(days=1)
    
    # Save
    df = pd.DataFrame(all_matches)
    csv_path = f"{OUTPUT_DIR}/mega_historical_2026-03.csv"
    df.to_csv(csv_path, index=False)
    
    print(f"\n{'='*60}")
    print(f"✅ {len(df)} total rows saved to {csv_path}")
    
    # Summary
    for sport in sorted(df['sport'].unique()):
        sub = df[df['sport']==sport]
        scored = sub.dropna(subset=['home_score'])
        with_pred = sub.dropna(subset=['prediction'])
        print(f"  {sport:15s}: {len(sub):6d} rows | {len(with_pred):5d} predictions | {len(scored):5d} with scores")
        if len(scored) > 0:
            avg_diff = scored['score_diff'].mean()
            print(f"    Avg score diff: {avg_diff:+.2f} ({'sous-évalué' if avg_diff>0 else 'surévalué'})")
    
    # Also save JSON
    json_path = f"{OUTPUT_DIR}/mega_historical_2026-03.json"
    with open(json_path, 'w') as f:
        json.dump(all_matches, f, ensure_ascii=False, default=str)

if __name__ == "__main__":
    main()
