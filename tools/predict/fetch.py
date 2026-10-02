"""Download past WeatherTech race/qualifying/practice results (JSON) from Al Kamel, gently, with a disk cache."""
import json, os, re, sys, time
from urllib.parse import quote, unquote
import requests
B = "https://imsa.results.alkamelcloud.com/"
S = requests.Session(); S.headers["User-Agent"] = "yellowcarpoints.win research (https://yellowcarpoints.win)"
OUT = "cache"; os.makedirs(OUT, exist_ok=True)
RANK = {"Official": 0, "Provisional": 1, "Unofficial": 2, "": 3}

def get(params=None, path=None):
    time.sleep(1.0)
    r = S.get(B + (quote(path) if path else ""), params=params, timeout=60); r.raise_for_status(); return r

def opts(html, name):
    m = re.search(rf'<select name="{name}".*?</select>', html, re.S)
    return [v for v, _ in re.findall(r'<option Value="([^"]+)"( SELECTED)?', m.group(0))] if m else []

seasons = sys.argv[1:] or ["23_2023", "24_2024", "25_2025", "26_2026"]
for season in seasons:
    for ev in opts(get({"season": season}).text, "evvent"):
        fn = f"{OUT}/{season}__{ev}.json"
        if os.path.exists(fn):
            continue
        html = get({"season": season, "evvent": ev}).text
        links = [unquote(h) for h in re.findall(r'href="([^"]+)"', html)]
        links = [l for l in links if "IMSA WeatherTech SportsCar Championship/" in l]
        want = {}
        for l in links:
            name = l.split("/")[-1]
            m = re.match(r"03_Results_(Race|Qualifying|Practice \d|Warm ?Up)(?:_(Official|Provisional|Unofficial))?\.JSON$", name)
            if m:
                hr = re.search(r"/(\d+)_Hour \d+/", l)
                k, rank = m.group(1), (-(int(hr.group(1)) if hr else 999), RANK[m.group(2) or ""])
                if k not in want or rank < want[k][0]:
                    want[k] = (rank, l)
        doc = {"season": season, "event": ev, "sessions": {}}
        for k, (_, l) in want.items():
            try:
                doc["sessions"][k] = json.loads(get(path=l).content.decode("utf-8-sig"))
            except Exception as e:
                print("fail", ev, k, e)
        json.dump(doc, open(fn, "w"))
        print(season, ev, sorted(doc["sessions"]))
