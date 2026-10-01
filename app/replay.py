"""Replay a recorded session through the live code, to see what it computed and debug it.

    python replay.py <archive session folder> <output dir> [--data /data] [--until N]

Copies the standings/baseline/quali/entries files from --data (default /data) into the
output dir, then feeds every recorded leaderboard poll (and the telemetry recorded up to
that moment) through live.step(). The output dir ends up with live.json, laps.json and
race_state.json as they were after poll N (or the last poll).

Telemetry was recorded every 10 seconds, so refuel durations come out up to ~10 s coarser
than they were live.
"""

import argparse
import gzip
import json
import os
import shutil
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("session")
ap.add_argument("out")
ap.add_argument("--data", default="/data")
ap.add_argument("--until", type=int, default=None, help="stop after this many polls")
args = ap.parse_args()

src, out = Path(args.session), Path(args.out)
out.mkdir(parents=True, exist_ok=True)
for name in ("standings.json", "baseline.json", "quali.json", "entries.json"):
    if (Path(args.data) / name).exists():
        shutil.copy(Path(args.data) / name, out / name)
os.environ["DATA_DIR"] = str(out)
sys.path.insert(0, str(Path(__file__).parent))

import archive  # noqa: E402  (DATA_DIR must be set first)
import live  # noqa: E402
import telemetry  # noqa: E402


def lines(name):
    p = src / name
    return [json.loads(l) for l in gzip.open(p, "rt", encoding="utf-8")] if p.exists() else []


feed, tel = lines("feed.jsonl.gz"), sorted(lines("telemetry.jsonl.gz"), key=lambda r: r["t"])
print(f"{len(feed)} polls, {len(tel)} telemetry records")

archive.RECORDER.start = lambda label: None
T = telemetry.Telemetry()
T.ensure = lambda on: None
T.ws = True  # report "connected"
live.TELEMETRY = T
live.refresh_schedule = lambda now: None
live._s["schedule"] = []
clock = [0.0]
live.time.time = lambda: clock[0]
current = {}
live.jsonp = lambda name: current["info"] if name == "SessionInfo" else current["results"]

ti, n = 0, 0
for n, poll in enumerate(feed[:args.until], 1):
    while ti < len(tel) and tel[ti]["t"] <= poll["t"]:
        r = tel[ti]
        with T.lock:
            if "session" in r:
                T.session = r["session"]
            for f in r.get("cars", []):
                T._car(f)
        T.last_data = r["t"]
        ti += 1
    clock[0] = poll["t"]
    current.update(info=poll["info"], results=poll["results"])
    live.step()

state = json.loads((out / "race_state.json").read_text()) if (out / "race_state.json").exists() else {}
print(f"replayed {n} polls; session {state.get('key')}; output in {out}")
