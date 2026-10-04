"""Audit the pit-strategy predictions against what happened at Petit Le Mans 2026."""
import gzip, json, math, os, statistics as st
from collections import defaultdict

A = "/home/joe/Work/yellowcarpoints/archive/2026-10-03_Motul_Petit_Le_Mans/outputs.jsonl.gz"
S = os.path.dirname(os.path.abspath(__file__))
snaps = []
with gzip.open(A, "rt") as fh:
    cur = {}
    for line in fh:
        d = json.loads(line)
        cur[d["name"]] = d["data"]
        if d["name"] == "laps.json" and "live.json" in cur:
            snaps.append({"t": d["t"], "live": cur["live.json"], "laps": d["data"]})
final = snaps[-1]["laps"]
res = json.load(open(f"{S}/results.json"))["classification"]
finish = defaultdict(list)
for r in res:
    finish[r["class"]].append(r["number"])
CLS = ["GTP", "LMP2", "GTDPRO", "GTD"]

def hms(t):
    try:
        h, m, s = (float(x) for x in str(t).split(":")); return h * 3600 + m * 60 + s
    except Exception:
        return None

def flag_at(flags, lap):
    k = "green"
    for l, kind in flags or []:
        if l <= lap: k = kind
        else: break
    return k

def pct(v, q):
    v = sorted(v); return v[min(len(v) - 1, int(q * (len(v) - 1)))] if v else None

def summ(v):
    return f"n={len(v)} median {st.median(v):+.1f} | MAE {st.mean(abs(x) for x in v):.1f} | 10–90% {pct(v,.1):+.0f}..{pct(v,.9):+.0f}" if v else "n=0"

def green_use(d, flags, down):
    pit = {x for s in d.get("stops", []) for x in (s, s + 1, s + 2)}
    en, drops = d.get("energy") or [], []
    for (m, e0), (n, e) in zip(en, en[1:]):
        if n == m + 1 and n not in pit and flag_at(flags, n + down) == "green" and flag_at(flags, m + down) == "green" and 0.5 < e0 - e < 6:
            drops.append(e0 - e)
    return st.median(drops[-8:]) if len(drops[-8:]) >= 3 else None

print("snapshots:", len(snaps), "| race end laps", {c: max(len(v["laps"]) for v in final["classes"][c].values()) for c in CLS})

# --- A. next stop lap: predicted vs actual -------------------------------------------------------
print("\n== A. Next stop lap (actual - predicted), green-flag snapshots, cars with telemetry")
errs = defaultdict(lambda: defaultdict(list))   # method -> horizon bucket -> errors
why = defaultdict(int)
for sn in snaps:
    lv = sn["live"]
    if not lv.get("is_race") or "green" not in (lv.get("flag") or "").lower():
        continue
    for cls in ("GTDPRO", "GTD", "GTP"):
        c = lv["classes"].get(cls) or {}
        rows = c.get("cars", []); lead = max((int(r.get("laps") or 0) for r in rows), default=0)
        flags = sn["laps"]["flags"].get(cls)
        for r in rows:
            e = r.get("energy") or {}; lap = int(r.get("laps") or 0)
            stops = final["classes"][cls].get(r["car"], {}).get("stops", [])
            nxt = next((s for s in stops if s >= lap), None)
            if nxt is None or r.get("in_pit"):
                continue
            stop_flag = flag_at(final["flags"].get(cls), nxt + (lead - lap))
            if e.get("next_stop_lap"):
                h = e["next_stop_lap"] - lap
                b = "≤10" if h <= 10 else "11–25" if h <= 25 else "26+"
                errs[("telemetry last-5", stop_flag)][b].append(nxt - e["next_stop_lap"])
            gu = green_use(sn["laps"]["classes"][cls].get(r["car"], {}), flags, lead - lap)
            if gu and e.get("now") is not None:
                pred = lap + int(e["now"] / gu)
                h = pred - lap
                b = "≤10" if h <= 10 else "11–25" if h <= 25 else "26+"
                errs[("green-lap use", stop_flag)][b].append(nxt - pred)
for (m, fl), bk in sorted(errs.items()):
    for b in ("≤10", "11–25", "26+"):
        if bk[b]: print(f"  {m:17s} stop under {fl:6s} horizon {b:5s}: {summ(bk[b])}")

# --- A2. how far tanks actually go: laps per stint vs predicted full-tank laps, green stops only --
print("\n== A2. Fuel range: telemetry energy at pit entry (how empty cars came in), by class")
for cls in ("GTDPRO", "GTD", "GTP"):
    e_in = []
    for car, d in final["classes"][cls].items():
        en = dict((n, e) for n, e in d.get("energy") or [])
        for s in d.get("stops", []):
            if s in en: e_in.append(en[s])
    print(f"  {cls}: energy at the in-lap end, % of tank: median {st.median(e_in):.0f}, 10–90% {pct(e_in,.1):.0f}..{pct(e_in,.9):.0f} (n={len(e_in)})")

# --- B. stops to the flag ----------------------------------------------------------------------
print("\n== B. Stops to the flag (actual - predicted), by time left")
sb = defaultdict(list)
for sn in snaps:
    lv = sn["live"]; rem = hms(lv.get("remaining"))
    if not lv.get("is_race") or rem is None:
        continue
    for cls in ("GTDPRO", "GTD", "GTP"):
        for r in (lv["classes"].get(cls) or {}).get("cars", []):
            e = r.get("energy") or {}
            if e.get("stops_remaining") is None: continue
            stops = final["classes"][cls].get(r["car"], {}).get("stops", [])
            after = sum(1 for s in stops if s > int(r.get("laps") or 0))
            b = "<2h" if rem < 7200 else "2–5h" if rem < 18000 else "5h+"
            sb[b].append(after - e["stops_remaining"])
for b in ("5h+", "2–5h", "<2h"):
    print(f"  {b:5s}: {summ(sb[b])}")

# --- C. what a stop cost: in-lap + stop lap against the cars that didn't pit on those laps ------
print("\n== C. Stop cost this race (in-lap + stop lap vs same-lap class median), seconds")
for cls in CLS:
    cars = final["classes"][cls]; flags = final["flags"].get(cls)
    lead = max(len(d["laps"]) for d in cars.values())
    bylap = defaultdict(list)
    for d in cars.values():
        pit = {x for s in d.get("stops", []) for x in (s, s + 1, s + 2)}
        for n, t in d["laps"]:
            if n > 1 and n not in pit: bylap[n].append(t)
    med = {n: st.median(v) for n, v in bylap.items() if len(v) >= 3}
    g, y = [], []
    for car, d in cars.items():
        L = dict(d["laps"]); down = lead - len(d["laps"])
        for s in d.get("stops", []):
            if s in L and s + 1 in L and s in med and s + 1 in med:
                loss = L[s] + L[s + 1] - med[s] - med[s + 1]
                k1, k2 = flag_at(flags, s + down), flag_at(flags, s + 1 + down)
                if 10 < loss < 250:
                    (g if k1 == k2 == "green" else y if k1 == k2 == "yellow" else []).append(loss)
    print(f"  {cls:6s} green: median {st.median(g):.1f} s (n={len(g)}, IQR {pct(g,.25):.0f}–{pct(g,.75):.0f}) | yellow: median {st.median(y) if y else float('nan'):.1f} s (n={len(y)})")

# --- D. laps to go -----------------------------------------------------------------------------
print("\n== D. Laps to go: actual laps the class leader completed after the snapshot vs remaining / pace")
dd = defaultdict(list); ratio = defaultdict(list)
for sn in snaps:
    lv = sn["live"]; rem = hms(lv.get("remaining"))
    if not lv.get("is_race") or not rem or rem < 1800: continue
    for cls in ("GTDPRO", "GTP"):
        c = lv["classes"].get(cls) or {}; pace = (c.get("strategy") or {}).get("class_pace")
        lead = max((int(r.get("laps") or 0) for r in c.get("cars", [])), default=0)
        endl = max(len(d["laps"]) for d in final["classes"][cls].values())
        if pace:
            pred = rem / pace; act = endl - lead
            dd[cls].append(act - pred); ratio[cls].append(act / pred)
for cls in dd:
    print(f"  {cls}: actual - predicted laps {summ(dd[cls])} | actual/predicted median {st.median(ratio[cls]):.2f}")
for cls in ("GTDPRO", "GTP"):
    cars = final["classes"][cls]; flags = final["flags"].get(cls)
    w = max(cars.values(), key=lambda d: len(d["laps"]))
    gl = [t for n, t in w["laps"] if flag_at(flags, n) == "green" and t < 200]
    al = [t for n, t in w["laps"] if t < 2000]
    print(f"  {cls}: winner's median green lap {st.median(gl):.1f} s, average lap including yellows {st.mean(al):.1f} s -> race laps run at {st.median(gl)/st.mean(al):.2f} of green pace")

# --- E. net position vs final result -------------------------------------------------------------
print("\n== E. Rank correlation with the final class order (Spearman), green snapshots")
def spearman(a, b):
    common = [x for x in a if x in b]
    if len(common) < 4: return None
    ra = {x: i for i, x in enumerate([x for x in a if x in common])}; rb = {x: i for i, x in enumerate([x for x in b if x in common])}
    n = len(common); return 1 - 6 * sum((ra[x] - rb[x]) ** 2 for x in common) / (n * (n * n - 1))
corr = defaultdict(lambda: defaultdict(list))
for sn in snaps:
    lv = sn["live"]; rem = hms(lv.get("remaining"))
    if not lv.get("is_race") or rem is None or "green" not in (lv.get("flag") or "").lower(): continue
    b = "last 2h" if rem < 7200 else "2–5h left" if rem < 18000 else "5h+ left"
    for cls in CLS:
        rows = (lv["classes"].get(cls) or {}).get("cars", [])
        track = [r["car"] for r in sorted(rows, key=lambda r: r["class_pos"])]
        net = [r["car"] for r in sorted(rows, key=lambda r: r.get("net_pos") or 99)] if all(r.get("net_pos") for r in rows) else None
        s1 = spearman(track, finish[cls]);
        if s1 is not None: corr[b]["track position"].append(s1)
        if net:
            s2 = spearman(net, finish[cls])
            if s2 is not None: corr[b]["net position (scraper)"].append(s2)
for b in ("5h+ left", "2–5h left", "last 2h"):
    print("  " + b + ": " + " | ".join(f"{k} {st.mean(v):.2f} (n={len(v)})" for k, v in corr[b].items()))

json.dump({"finish": finish}, open(f"{S}/finish.json", "w"))
