"""Race result prediction: a Plackett-Luce model on pre-race features, fitted to past WeatherTech races.

Each car gets a strength s = w . features; the finishing order in a class is modelled as picking the
winner with probability exp(s_i) / sum exp(s_j), then 2nd from the rest, and so on. Weights are fitted
by maximum likelihood (with a little L2), and race length scales strength down (longer = more random).
"""
import glob, json, math, random, re, statistics, sys
from collections import defaultdict

CLASSES = ["GTP", "LMP2", "GTDPRO", "GTD"]
FEATS = ["q_rank", "q_gap", "p_gap", "form", "dnf", "trk", "make", "bronze"]
TOPK = 99


def secs(t):
    if not t: return None
    try:
        v = 0.0
        for p in str(t).split(":"): v = v * 60 + float(p)
        return v
    except ValueError:
        return None


def load(paths):
    races = []
    for f in sorted(paths):
        d = json.load(open(f))
        s = d["sessions"]
        if "Race" not in s and "Qualifying" not in s: continue
        sess = (s.get("Race") or s["Qualifying"])["session"]
        races.append({"season": d["season"][3:], "event": d["event"].split("_", 1)[1], "circuit": sess["circuit"]["name"],
                      "hours": (s["Race"]["session"]["finalize_type"].get("time_in_seconds") or 9600) / 3600 if "Race" in s else None,
                      "s": s})
    return races


def class_order(rows, cls, key="position"):
    return [r for r in sorted((r for r in rows if r["class"] == cls), key=lambda r: r[key])]


def pace(rows, cls, field="time"):
    """car -> % behind the class best lap (capped)."""
    t = {r["number"]: secs(r.get(field)) for r in rows if r["class"] == cls}
    t = {k: v for k, v in t.items() if v}
    if not t: return {}
    best = min(t.values())
    return {k: min(3.0, (v / best - 1) * 100) for k, v in t.items()}


def build(races, upto=None):
    """Feature rows for every race (class by class), using only information from before that race."""
    out = []
    hist = defaultdict(list)       # (season, car, cls) -> [finish pct]
    dnfs = defaultdict(list)
    make_hist = defaultdict(list)  # (season, make, cls) -> [finish pct]
    track = {}                     # (season, circuit, car, cls) -> finish pct
    for race in races:
        s, season = race["s"], race["season"]
        q = s.get("Qualifying", {}).get("classification", [])
        prac = [s[k]["classification"] for k in s if k.startswith("Practice")]
        res = s.get("Race", {}).get("classification")
        for cls in CLASSES:
            entry = class_order(res, cls) if res else class_order(q, cls)
            if len(entry) < 3: continue
            qo = [r["number"] for r in class_order(q, cls)]
            qg = pace(q, cls)
            pg = {}
            for p in prac:
                for k, v in pace(p, cls).items(): pg[k] = min(pg.get(k, 9), v)
            n = len(entry)
            cars = []
            for r in entry:
                car, make = r["number"], r.get("manufacturer") or r.get("vehicle", "").split()[0]
                prev = str(int(season) - 1)
                h, dn, mh = hist[(season, car, cls)], dnfs[(season, car, cls)], make_hist[(season, make, cls)]
                qpos = qo.index(car) if car in qo else len(qo)
                cars.append({
                    "car": car, "team": r["team"], "make": make,
                    "q_rank": qpos / max(1, n - 1),
                    "q_gap": qg.get(car, 3.0),
                    "p_gap": pg.get(car, 3.0) if pg else 1.0,
                    "form": (sum(h[-6:]) + 0.5 * 2) / (len(h[-6:]) + 2),
                    "form2": (sum(h[-6:]) + 0.5 * sum(hist[(prev, car, cls)][-6:]) + 0.5 * 2) / (len(h[-6:]) + 0.5 * len(hist[(prev, car, cls)][-6:]) + 2),
                    "dnf": (sum(dn) + 0.15 * 2) / (len(dn) + 2),
                    "trk": track.get((prev, race["circuit"], car, cls), 0.5),
                    "make": (sum(mh[-12:]) + 0.5 * 3) / (len(mh[-12:]) + 3),
                    "bronze": sum(1 for d in r.get("drivers", []) if d.get("license") == "Bronze"),
                    "out": bool(r.get("not_finished")) if res else None,
                })
            out.append({"season": season, "event": race["event"], "circuit": race["circuit"], "hours": race["hours"],
                        "cls": cls, "cars": cars, "done": bool(res)})
            if res:
                for i, r in enumerate(entry):
                    car, make = r["number"], r.get("manufacturer") or r.get("vehicle", "").split()[0]
                    pct = i / max(1, n - 1)
                    hist[(season, car, cls)].append(pct)
                    dnfs[(season, car, cls)].append(1 if r.get("not_finished") else 0)
                    make_hist[(season, make, cls)].append(pct)
                    track[(season, race["circuit"], car, cls)] = pct
    return out


def strength(c, w, scale):
    return scale * sum(w[f] * c[f] for f in FEATS)


def scale_of(hours, beta):
    return math.exp(-beta * math.log(max(hours or 2.67, 1) / 2.67))


def loglik(groups, w, beta, grad=False):
    ll, g = 0.0, {f: 0.0 for f in FEATS}
    for grp in groups:
        sc = scale_of(grp["hours"], beta)
        cars = grp["cars"]
        s = [strength(c, w, sc) for c in cars]
        # Plackett-Luce over the full finishing order (cars are already in finishing order).
        for i in range(min(len(cars) - 1, TOPK)):
            m = max(s[i:])
            e = [math.exp(x - m) for x in s[i:]]
            z = sum(e)
            ll += s[i] - m - math.log(z)
            if grad:
                for f in FEATS:
                    exp_f = sum(ei * c[f] for ei, c in zip(e, cars[i:])) / z
                    g[f] += sc * (cars[i][f] - exp_f)
    return ll, g


def fit(groups, l2=1.0, iters=400, betas=(0.0, 0.2, 0.4, 0.6)):
    """Maximum likelihood with L2 (Adam steps); beta (race-length damping) by grid search."""
    best = None
    for beta in betas:
        w = {f: 0.0 for f in FEATS}
        m1 = {f: 0.0 for f in FEATS}; m2 = {f: 0.0 for f in FEATS}
        for t in range(1, iters + 1):
            ll, g = loglik(groups, w, beta, grad=True)
            for f in FEATS:
                gf = g[f] - l2 * w[f]
                m1[f] = 0.9 * m1[f] + 0.1 * gf; m2[f] = 0.999 * m2[f] + 0.001 * gf * gf
                w[f] += 0.05 * (m1[f] / (1 - 0.9 ** t)) / (math.sqrt(m2[f] / (1 - 0.999 ** t)) + 1e-8)
        ll, _ = loglik(groups, w, beta)
        ll -= 0.5 * l2 * sum(v * v for v in w.values())
        if best is None or ll > best[0]:
            best = (ll, w, beta)
    return best[1], best[2]


def simulate(grp, w, beta, n=20000, seed=1):
    """Monte Carlo finishing orders (Gumbel trick = Plackett-Luce sampling)."""
    rnd = random.Random(seed)
    sc = scale_of(grp["hours"], beta)
    s = [strength(c, w, sc) for c in grp["cars"]]
    k = len(s)
    pos = [[0] * k for _ in range(k)]
    for _ in range(n):
        noisy = sorted(range(k), key=lambda i: -(s[i] - math.log(-math.log(rnd.random() or 1e-12))))
        for p, i in enumerate(noisy): pos[i][p] += 1
    return [[x / n for x in row] for row in pos]
