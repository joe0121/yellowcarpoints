import json, statistics as st
from collections import defaultdict
exec(open("audit.py").read().split("# --- A. next stop lap")[0])   # loaders and helpers

print("== A2. Fuel left when cars pitted (energy on the lap before the in-lap), %")
for cls in ("GTDPRO", "GTD", "GTP"):
    flags = final["flags"].get(cls); lead = max(len(d["laps"]) for d in final["classes"][cls].values())
    g, y = [], []
    for car, d in final["classes"][cls].items():
        en = dict((n, e) for n, e in d.get("energy") or []); down = lead - len(d["laps"])
        for s in d.get("stops", []):
            if s - 1 in en: (g if flag_at(flags, s + down) == "green" else y).append(en[s - 1])
    print(f"  {cls}: stops under green: median {st.median(g):.0f}% left (10–90% {pct(g,.1):.0f}..{pct(g,.9):.0f}, n={len(g)}) | under yellow: median {st.median(y):.0f}% (n={len(y)})")

print("\n== B2. Stops made vs the fuel-only minimum (laps / laps per tank)")
for cls in ("GTDPRO", "GTD", "GTP"):
    made, need = [], []
    for car, d in final["classes"][cls].items():
        en = d.get("energy") or []
        drops = [e0 - e for (m, e0), (n, e) in zip(en, en[1:]) if n == m + 1 and 0.5 < e0 - e < 6]
        if len(drops) < 20: continue
        made.append(len(d["stops"])); need.append(len(d["laps"]) * st.median(drops) / 100 - 1)
    print(f"  {cls}: stops made median {st.median(made)}, fuel-only minimum median {st.median(need):.1f}")

print("\n== E2. Fuel-based net to the flag (the page's method, re-created) vs the final order")
def spearman(a, b):
    common = [x for x in a if x in b]
    if len(common) < 4: return None
    ra = {x: i for i, x in enumerate([x for x in a if x in common])}; rb = {x: i for i, x in enumerate([x for x in b if x in common])}
    n = len(common); return 1 - 6 * sum((ra[x] - rb[x]) ** 2 for x in common) / (n * (n * n - 1))
def gap_s(r, pace):
    if r["class_pos"] == 1: return 0.0
    g = str(r.get("gap") or "")
    import re
    m = re.match(r"-?(\d+) laps?", g.strip())
    if m: return int(m.group(1)) * pace
    try: return float(g)
    except ValueError: return None
corr = defaultdict(lambda: defaultdict(list))
for sn in snaps:
    lv = sn["live"]; rem = hms(lv.get("remaining"))
    if not lv.get("is_race") or rem is None or "green" not in (lv.get("flag") or "").lower(): continue
    b = "last 2h" if rem < 7200 else "2–5h left" if rem < 18000 else "5h+ left"
    for cls in ("GTDPRO", "GTD", "GTP"):
        c = lv["classes"].get(cls) or {}; rows = c.get("cars", [])
        pace = (c.get("strategy") or {}).get("class_pace")
        if not pace or not rows: continue
        lead = max(int(r.get("laps") or 0) for r in rows); flags = sn["laps"]["flags"].get(cls)
        for factor, name in ((1.0, "fuel net"), (0.8, "fuel net, cautions allowed")):
            togo = rem / pace * factor; owed = {}
            for r in rows:
                e = r.get("energy") or {}
                use = green_use(sn["laps"]["classes"][cls].get(r["car"], {}), flags, lead - int(r.get("laps") or 0)) or e.get("use_per_lap")
                if use and e.get("now") is not None:
                    need = max(0, togo * use - (100 if r.get("in_pit") else e["now"])) / 100
                    owed[r["car"]] = need * (20 + 40)
            if len(owed) < len(rows) / 2: continue
            least = min(owed.values())
            net = sorted(rows, key=lambda r: (gap_s(r, pace) if gap_s(r, pace) is not None else 1e6) + owed.get(r["car"], least) - least)
            s = spearman([r["car"] for r in net], finish[cls])
            if s is not None: corr[b][name].append(s)
        s = spearman([r["car"] for r in sorted(rows, key=lambda r: r["class_pos"])], finish[cls])
        if s is not None: corr[b]["track position"].append(s)
for b in ("5h+ left", "2–5h left", "last 2h"):
    print("  " + b + ": " + " | ".join(f"{k} {st.mean(v):.2f}" for k, v in corr[b].items()))

print("\n== F. In-race win predictions vs the winners")
pred = json.load(open(os.path.join(S, "predict.json")))
for cls in CLS:
    w = finish[cls][0]
    row = []
    for h in pred["history"]:
        p = h["win"].get(cls, {})
        if p: row.append(f'{h["label"]}: {p.get(w, 0):.0%}' + (" (fav)" if max(p, key=p.get) == w else ""))
    print(f"  {cls} winner #{w}: " + ", ".join(row))
