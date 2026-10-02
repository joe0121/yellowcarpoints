"""Petit Le Mans time cards (CSV, has FLAG_AT_FL) for every season: keep per-lap flag + time for every car."""
import csv, io, json, os, re, time
from urllib.parse import quote, unquote
import requests
B = "https://imsa.results.alkamelcloud.com/"
S = requests.Session(); S.headers["User-Agent"] = "yellowcarpoints.win research (https://yellowcarpoints.win)"
def opts(html, name):
    m = re.search(rf'<select name="{name}".*?</select>', html, re.S)
    return [v for v, _ in re.findall(r'<option Value="([^"]+)"( SELECTED)?', m.group(0))] if m else []
for season in [f"{y % 100:02d}_{y}" for y in range(2014, 2026)]:
    fn = f"plm/{season}.json"
    if os.path.exists(fn): continue
    time.sleep(1)
    evs = [e for e in opts(S.get(B, params={"season": season}, timeout=60).text, "evvent") if "Road Atlanta" in e or "Petit" in e]
    if not evs: print("no event", season); continue
    ev = evs[-1]; time.sleep(1)
    html = S.get(B, params={"season": season, "evvent": ev}, timeout=60).text
    best = None
    for l in (unquote(h) for h in re.findall(r'href="([^"]+)"', html)):
        if "WeatherTech" in l and "_Race/" in l and re.search(r"/23_Time Cards_Race[^/]*\.CSV$", l):
            hr = re.search(r"/(\d+)_Hour \d+/", l); key = (0 if not hr else 1, -(int(hr.group(1)) if hr else 0), "Unofficial" in l)
            if best is None or key < best[0]: best = (key, l)
    if not best: print("no timecards", season, ev); continue
    time.sleep(1)
    txt = S.get(B + quote(best[1]), timeout=300).content.decode("utf-8-sig", "replace")
    rows = csv.reader(io.StringIO(txt), delimiter=";")
    head = [h.strip() for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    laps = []
    for r in rows:
        if len(r) < len(head) - 1: continue
        g = lambda k: r[ix[k]].strip() if k in ix and ix[k] < len(r) else ""
        laps.append([g("NUMBER"), g("CLASS"), int(g("LAP_NUMBER") or 0), g("LAP_TIME"), g("ELAPSED"), g("FLAG_AT_FL"), g("CROSSING_FINISH_LINE_IN_PIT")])
    json.dump({"season": season, "event": ev, "file": best[1], "has_flag": "FLAG_AT_FL" in ix, "laps": laps}, open(fn, "w"))
    print(season, ev, len(laps), "flag col" if "FLAG_AT_FL" in ix else "NO FLAG COL")
