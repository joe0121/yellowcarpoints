"""The other titles: Manufacturers' championship and the Michelin Endurance Cup (teams and manufacturers).

Al Kamel publishes every standings table as JSON in each event's "Points Data - Official" (or
"- Provisional") folder: "IWSC 10 GTDPRO Manufacturers.json" for the main championship, and
"09 IMEC GT Daytona PRO Teams Standings Overall.json" etc. for the Endurance Cup (only at endurance
rounds). We take the newest event that has each, Official over Provisional, and write titles.json.
Checked with the championship points (every INTERVAL_MINUTES).
"""

import json
import logging
import re
from urllib.parse import quote, unquote

from common import now_iso, read, write

log = logging.getLogger("scraper.titles")
IWSC = {"GTP": "GTP", "LMP2": "LMP2", "GTDPRO": "GTDPRO", "GTD": "GTD"}
IMEC = {"GTP": "GTP", "LMP2": "LMP2", "GTDPRO": "GT Daytona PRO", "GTD": "GT Daytona"}
RANK = {"Official": 0, "Provisional": 1}


def _links(html):
    """{file name: (status, path)} for the Points Data JSON files on an event page, Official first."""
    out = {}
    for link in (unquote(h) for h in re.findall(r'href="([^"]+)"', html)):
        m = re.search(r"/Points Data - (Official|Provisional)[^/]*/([^/]+\.json)$", link)
        if m and "WeatherTech" in link and (m.group(2) not in out or RANK[m.group(1)] < RANK[out[m.group(2)][0]]):
            out[m.group(2)] = (m.group(1), link)
    return out


def _table(http, base, path, kind):
    d = json.loads(http.get(base + quote(path), timeout=60).content.decode("utf-8-sig"))
    sessions = d.get("championship", {}).get("sessions", [])
    rows, scored = [], set()
    for r in d.get("classification", []):
        for s in r.get("points_by_session", []):
            if s.get("total_points"):
                scored.add(s["session_index"])
        row = {"pos": r.get("position"), "points": r.get("total_points")}
        if kind == "teams":
            row.update(car=str(r.get("key", "")), team=r.get("team", ""))
        else:
            row["make"] = r.get("key") or r.get("name") or ""
        rows.append(row)
    events, done = [], []
    for s in sessions:
        if s["event_name"] not in events:
            events.append(s["event_name"])
        if s["session_index"] in scored and s["event_name"] not in done:
            done.append(s["event_name"])
    return {"standings": rows, "events": events, "events_done": done,
            "title": d.get("championship", {}).get("main_title", "")}


def refresh(http, base, page, options):
    seasons, current = options(page(), "season")
    events, _ = options(page(current), "evvent")
    want_mfr = {cls: f"IWSC {n:02d} {name} Manufacturers.json" for cls, (n, name) in
                {"GTP": (3, "GTP"), "GTDPRO": (10, "GTDPRO"), "GTD": (13, "GTD")}.items()}
    want_mec = {}
    for cls, name in IMEC.items():
        want_mec[(cls, "teams")] = re.compile(rf"^\d+ IMEC {re.escape(name)} Teams Standings Overall\.json$")
        if cls != "LMP2":
            want_mec[(cls, "manufacturers")] = re.compile(rf"^\d+ IMEC {re.escape(name)} Manufacturers Standings Overall\.json$")
    out = {"updated": now_iso(), "season": current.split("_", 1)[1], "manufacturers": {}, "endurance": {}}
    for ev in reversed(events):
        if not want_mfr and not want_mec:
            break
        files = _links(page(current, ev))
        if not files:
            continue
        evname = ev.split("_", 1)[1]
        for cls, name in list(want_mfr.items()):
            if name in files:
                status, path = files[name]
                out["manufacturers"][cls] = {"event": evname, "status": status, **_table(http, base, path, "manufacturers")}
                del want_mfr[cls]
        for (cls, kind), rx in list(want_mec.items()):
            hit = next((f for f in files if rx.match(f)), None)
            if hit:
                status, path = files[hit]
                e = out["endurance"].setdefault(cls, {"event": evname, "status": status})
                e[kind] = _table(http, base, path, kind)
                del want_mec[(cls, kind)]
    old = read("titles.json") or {}
    if {k: v for k, v in out.items() if k != "updated"} != {k: v for k, v in old.items() if k != "updated"}:
        write("titles.json", out)
        log.info("titles: manufacturers %s, endurance %s", sorted(out["manufacturers"]), sorted(out["endurance"]))
    return out
