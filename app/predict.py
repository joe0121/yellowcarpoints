"""Race prediction: a Plackett-Luce model on pre-race features, fitted to past WeatherTech races.

Each car gets a strength s = w . features. A class's finishing order is modelled as drawing the winner
with probability exp(s_i) / sum exp(s_j), then 2nd from the rest, and so on (fitted on the top 3 of each
class, which suits win and podium odds). Features, all known before the race: starting position, best
practice lap, form (this season, last season at half weight), retirement rate, Bronze drivers.

Past results (JSON, 2024 on) come from Al Kamel's results site, one event page and a few files per
event, cached in CACHE_DIR so each event is downloaded once.
"""

import json
import logging
import math
import os
import random
import re
import statistics
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote, unquote

from common import http

log = logging.getLogger("analyst.predict")
BASE = "https://imsa.results.alkamelcloud.com/"
CACHE = Path(os.environ.get("CACHE_DIR", "/cache")) / "results"
CLASSES = ["GTP", "LMP2", "GTDPRO", "GTD"]
FEATS = ["q_rank", "p_gap", "form2", "dnf", "bronze"]
FEATURE_NAMES = {"q_rank": "starting position", "p_gap": "best practice lap", "form2": "recent form",
                 "dnf": "retirement rate", "bronze": "Bronze drivers"}
TOPK = 3
FIRST_SEASON = 2024           # Al Kamel's JSON results start here
RACE_POINTS = [350, 320, 300, 280, 260, 250, 240, 230, 220, 210, 200, 190, 180, 170, 160, 150, 140, 130, 120, 110, 100, 90, 80, 70, 60, 50, 40, 30, 20, 10]
RANK = {"Official": 0, "Provisional": 1, "Unofficial": 2, "": 3}


def race_pts(p):
    return RACE_POINTS[p - 1] if 1 <= p <= len(RACE_POINTS) else 0


def quali_pts(p):
    return race_pts(p) // 10


def secs(t):
    if not t:
        return None
    try:
        v = 0.0
        for p in str(t).split(":"):
            v = v * 60 + float(p)
        return v
    except ValueError:
        return None


# --- fetching ----------------------------------------------------------------------

def _get(params=None, path=None):
    time.sleep(1.0)       # gentle: one request a second
    r = http.get(BASE + (quote(path) if path else ""), params=params, timeout=120)
    r.raise_for_status()
    return r


def options(html, name):
    m = re.search(rf'<select name="{name}".*?</select>', html, re.S)
    return [v for v, _ in re.findall(r'<option Value="([^"]+)"( SELECTED)?', m.group(0))] if m else []


def fetch_results(seasons, current=None):
    """Race/qualifying/practice results per event, cached. The current weekend (events in the last season
    whose name contains `current`) is always fetched again, as its files are still appearing."""
    CACHE.mkdir(parents=True, exist_ok=True)
    for season in seasons:
        for ev in options(_get({"season": season}).text, "evvent"):
            fn = CACHE / f"{season}__{ev}.json"
            now = bool(current) and season == seasons[-1] and current.lower() in ev.lower()
            if fn.exists() and not now:
                cached = json.loads(fn.read_text())["sessions"]
                if "Race" in cached or not cached:       # complete, or no WeatherTech sessions at all
                    continue                             # (a weekend cached before its race is fetched again)
            html = _get({"season": season, "evvent": ev}).text
            want = {}
            for link in (unquote(h) for h in re.findall(r'href="([^"]+)"', html)):
                if "IMSA WeatherTech SportsCar Championship/" not in link:
                    continue
                m = re.match(r"03_Results_(Race|Qualifying|Practice \d)(?:_(Official|Provisional|Unofficial))?\.JSON$", link.split("/")[-1])
                if m:
                    hr = re.search(r"/(\d+)_Hour \d+/", link)
                    key = (-(int(hr.group(1)) if hr else 999), RANK[m.group(2) or ""])
                    if m.group(1) not in want or key < want[m.group(1)][0]:
                        want[m.group(1)] = (key, link)
            doc = {"season": season, "event": ev, "sessions": {}}
            for k, (_, link) in want.items():
                try:
                    doc["sessions"][k] = json.loads(_get(path=link).content.decode("utf-8-sig"))
                except Exception:
                    log.exception("results %s %s %s", season, ev, k)
            fn.write_text(json.dumps(doc))
    return load(sorted(CACHE.glob("*.json")))


def load(paths):
    races = []
    for f in sorted(paths):
        d = json.loads(Path(f).read_text())
        s = d["sessions"]
        if "Race" not in s and "Qualifying" not in s:
            continue
        sess = (s.get("Race") or s["Qualifying"])["session"]
        races.append({"season": d["season"][3:], "event": d["event"].split("_", 1)[1], "circuit": sess["circuit"]["name"],
                      "hours": (s["Race"]["session"]["finalize_type"].get("time_in_seconds") or 9600) / 3600 if "Race" in s else None,
                      "s": s})
    return races


# --- features and model ------------------------------------------------------------

def class_order(rows, cls):
    return sorted((r for r in rows if r["class"] == cls), key=lambda r: r["position"])


def pace(rows, cls):
    t = {r["number"]: secs(r.get("time")) for r in rows if r["class"] == cls}
    t = {k: v for k, v in t.items() if v}
    if not t:
        return {}
    best = min(t.values())
    return {k: min(3.0, (v / best - 1) * 100) for k, v in t.items()}


def make_of(r):
    return r.get("manufacturer") or (r.get("vehicle") or "").split(" ")[0]


def build(races):
    """Feature rows per race and class, each using only what was known before that race."""
    out, hist, dnfs = [], defaultdict(list), defaultdict(list)
    for race in races:
        s, season = race["s"], race["season"]
        prev = str(int(season) - 1)
        q = s.get("Qualifying", {}).get("classification", [])
        prac = [s[k]["classification"] for k in s if k.startswith("Practice")]
        res = s.get("Race", {}).get("classification")
        for cls in CLASSES:
            entry = class_order(res, cls) if res else class_order(q, cls)
            if len(entry) < 3:
                continue
            qo = [r["number"] for r in class_order(q, cls)]
            pg = {}
            for p in prac:
                for k, v in pace(p, cls).items():
                    pg[k] = min(pg.get(k, 9), v)
            n, cars = len(entry), []
            for r in entry:
                car = r["number"]
                h, hp, dn = hist[(season, car, cls)][-6:], hist[(prev, car, cls)][-6:], dnfs[(season, car, cls)]
                cars.append({
                    "car": car, "team": r["team"], "make": make_of(r),
                    "q_rank": (qo.index(car) if car in qo else len(qo)) / max(1, n - 1),
                    "p_gap": pg.get(car, 3.0) if pg else 1.0,
                    "form2": (sum(h) + 0.5 * sum(hp) + 0.5 * 2) / (len(h) + 0.5 * len(hp) + 2),
                    "dnf": (sum(dn) + 0.15 * 2) / (len(dn) + 2),
                    "bronze": sum(1 for d in r.get("drivers", []) if d.get("license") == "Bronze"),
                })
            out.append({"season": season, "event": race["event"], "circuit": race["circuit"], "hours": race["hours"],
                        "cls": cls, "cars": cars, "done": bool(res)})
            if res:
                for i, r in enumerate(entry):
                    hist[(season, r["number"], cls)].append(i / max(1, n - 1))
                    dnfs[(season, r["number"], cls)].append(1 if r.get("not_finished") else 0)
    return out


def scale_of(hours, beta):
    return math.exp(-beta * math.log(max(hours or 2.67, 1) / 2.67))


def strength(c, w, sc):
    return sc * sum(w[f] * c[f] for f in FEATS)


def loglik(groups, w, beta, grad=False):
    ll, g = 0.0, {f: 0.0 for f in FEATS}
    for grp in groups:
        sc = scale_of(grp["hours"], beta)
        cars = grp["cars"]
        s = [strength(c, w, sc) for c in cars]
        for i in range(min(len(cars) - 1, TOPK)):
            m = max(s[i:])
            e = [math.exp(x - m) for x in s[i:]]
            z = sum(e)
            ll += s[i] - m - math.log(z)
            if grad:
                for f in FEATS:
                    g[f] += sc * (cars[i][f] - sum(ei * c[f] for ei, c in zip(e, cars[i:])) / z)
    return ll, g


def fit(groups, l2=1.0, iters=400, betas=(0.0, 0.2, 0.4, 0.6)):
    """Maximum likelihood with L2 (Adam steps); beta (longer race = more random) by grid search."""
    best = None
    for beta in betas:
        w = {f: 0.0 for f in FEATS}
        m1, m2 = dict.fromkeys(FEATS, 0.0), dict.fromkeys(FEATS, 0.0)
        for t in range(1, iters + 1):
            _, g = loglik(groups, w, beta, grad=True)
            for f in FEATS:
                gf = g[f] - l2 * w[f]
                m1[f] = 0.9 * m1[f] + 0.1 * gf
                m2[f] = 0.999 * m2[f] + 0.001 * gf * gf
                w[f] += 0.05 * (m1[f] / (1 - 0.9 ** t)) / (math.sqrt(m2[f] / (1 - 0.999 ** t)) + 1e-8)
        ll = loglik(groups, w, beta)[0] - 0.5 * l2 * sum(v * v for v in w.values())
        if best is None or ll > best[0]:
            best = (ll, w, beta)
    return best[1], best[2]


def backtest(groups):
    """Predict each of the last two seasons from the seasons before it."""
    seasons = sorted({g["season"] for g in groups if g["done"]})
    r = {"class_races": 0, "favourite_won": 0, "pole_won": 0, "favourite_podium": 0, "pole_podium": 0}
    tested = []
    for season in seasons[1:][-2:]:
        train = [g for g in groups if g["done"] and g["season"] < season]
        if not train:
            continue
        w, beta = fit(train)
        tested.append(season)
        for g in (g for g in groups if g["done"] and g["season"] == season):
            s = [strength(c, w, scale_of(g["hours"], beta)) for c in g["cars"]]
            fav = max(range(len(s)), key=lambda i: s[i])
            pole = min(range(len(s)), key=lambda i: g["cars"][i]["q_rank"])
            r["class_races"] += 1
            r["favourite_won"] += fav == 0
            r["pole_won"] += pole == 0
            r["favourite_podium"] += fav <= 2
            r["pole_podium"] += pole <= 2
    r["seasons"] = "–".join(tested[:1] + tested[-1:]) if tested else ""
    return r


# --- simulation --------------------------------------------------------------------

def title_base(cls, standings, quali):
    """Points before the race: the standings plus this weekend's qualifying points (if not in yet)."""
    st = (standings.get("classes", {}).get(cls) or {}).get("standings", [])
    q = (quali or {}).get("classes", {}).get(cls, {})
    banked = (quali or {}).get("base_event") == standings.get("event")
    return {x["car"]: x["points"] + (quali_pts(q[x["car"]]) if banked and x["car"] in q else 0) for x in st}


def summarise(cars, sample, base, n, extra=None):
    """Run n simulated finishing orders (sample() -> list of car indexes, winner first) into odds."""
    k = len(cars)
    pos = [[0] * k for _ in range(k)]
    champ = dict.fromkeys(base, 0.0)
    for _ in range(n):
        order = sample()
        tot = dict(base)
        for p, i in enumerate(order):
            pos[i][p] += 1
            if cars[i]["car"] in tot:
                tot[cars[i]["car"]] += race_pts(p + 1)
        if tot:
            best = max(tot.values())
            lead = [c for c, v in tot.items() if v == best]
            for c in lead:
                champ[c] += 1 / len(lead)
    rows = []
    for i, c in enumerate(cars):
        p = [x / n for x in pos[i]]
        rows.append({"car": c["car"], "team": c.get("team", ""), "win": round(p[0], 4), "podium": round(sum(p[:3]), 4),
                     "top5": round(sum(p[:5]), 4), "expected": round(sum((j + 1) * x for j, x in enumerate(p)), 2),
                     "dist": [round(x, 4) for x in p], **(extra[i] if extra else {})})
    rows.sort(key=lambda r: (-r["win"], r["expected"]))
    title = sorted(({"car": c, "points_now": base[c], "odds": round(v / n, 4)} for c, v in champ.items() if v), key=lambda r: -r["odds"])
    return {"cars": rows, "title": title}


def prerace(event, standings, quali, n=40000):
    """Fit on every finished race and simulate this weekend's: the pre-race prediction."""
    year = int(standings["season"])
    seasons = [f"{y % 100:02d}_{y}" for y in range(max(FIRST_SEASON, year - 2), year + 1)]
    races = fetch_results(seasons, current=event)
    groups = build(races)
    done = [g for g in groups if g["done"]]
    target = [g for g in groups if not g["done"] and g["season"] == str(year) and event.lower() in g["circuit"].lower()]
    if not target:
        log.info("no qualifying yet for %s: no prediction", event)
        return None
    w, beta = fit(done)
    hours = statistics.median([g["hours"] for g in done if event.lower() in g["circuit"].lower()] or [2.67])
    rnd = random.Random(7)
    out = {}
    for g in target:
        s = [strength(c, w, scale_of(hours, beta)) for c in g["cars"]]
        k = len(s)
        sample = lambda: sorted(range(k), key=lambda i: -(s[i] - math.log(-math.log(rnd.random() or 1e-12))))
        extra = [{"why": {"grid": round(c["q_rank"] * (k - 1)) + 1, "practice_gap": round(c["p_gap"], 2),
                          "form": round(c["form2"], 3), "dnf": round(c["dnf"], 3), "bronze": c["bronze"]}} for c in g["cars"]]
        out[g["cls"]] = summarise(g["cars"], sample, title_base(g["cls"], standings, quali), n, extra)
    log.info("pre-race prediction for %s from %d races", event, len({(g['season'], g['event']) for g in done}))
    return {"classes": out, "hours": hours, "weights": {k: round(v, 3) for k, v in w.items()}, "beta": beta,
            "races_used": len({(g["season"], g["event"]) for g in done}), "backtest": backtest(groups)}
