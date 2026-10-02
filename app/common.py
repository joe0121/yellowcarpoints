"""Settings and small helpers shared by the points scraper, race history and live timing."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

# Tracked cars as CLASS:NUMBER (class as printed in the points PDF: GTP, LMP2, GTDPRO, GTD).
DEFAULT_CARS = "GTDPRO:4,GTDPRO:3,GTDPRO:74,GTD:13,GTD:36,GTD:81,LMP2:73,LMP2:99"
CAR_CLASS = {c.split(":")[-1].strip(): (c.split(":")[0].strip() if ":" in c else os.environ.get("CLASS", "GTDPRO"))
             for c in (os.environ.get("CARS") or DEFAULT_CARS).split(",") if c.strip()}
CARS = list(CAR_CLASS)
CLASSES = list(dict.fromkeys(CAR_CLASS.values()))
# Race-only cars (CLASS:NUMBER): followed in live timing and on the Race page, no championship maths.
# Default: none (the LMP2 #73 and #99 are full championship cars in CARS now).
RACE_CARS = {c.split(":")[-1].strip(): c.split(":")[0].strip()
             for c in os.environ.get("RACE_CARS", "").split(",") if ":" in c}
RACE_CARS = {c: k for c, k in RACE_CARS.items() if c not in CAR_CLASS}
LIVE_CAR_CLASS = {**CAR_CLASS, **RACE_CARS}
LIVE_CLASSES = list(dict.fromkeys(LIVE_CAR_CLASS.values()))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

http = requests.Session()
http.headers["User-Agent"] = "yellowcarpoints.win standings tracker"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read(name):
    try:
        return json.loads((DATA_DIR / name).read_text())
    except (OSError, ValueError):
        return None


def write(name, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = DATA_DIR / f"{name}.tmp"
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    tmp.replace(DATA_DIR / name)
