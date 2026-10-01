"""Record what the live code saw, so a session can be inspected and replayed later.

One folder per scheduled WeatherTech session under DATA_DIR/archive (bind-mounted to
./archive on the host), each holding gzipped JSON lines:

- feed.jsonl.gz       every leaderboard poll: {"t", "info": SessionInfo, "results": RaceResults}
- telemetry.jsonl.gz  telemetry for the tracked classes every TELEMETRY_EVERY seconds, plus
                      every session message: {"t", "session"} or {"t", "cars": [raw car messages]}
- outputs.jsonl.gz    what the site was showing every OUTPUT_EVERY seconds: {"t", "name", "data"}

`replay.py` feeds a folder back through the live code.
"""

import gzip
import json
import re
import threading
import time

from common import CLASSES, DATA_DIR

ROOT = DATA_DIR / "archive"
TELEMETRY_EVERY = 10
OUTPUT_EVERY = 300


class Recorder:
    def __init__(self):
        self.dir = None
        self.lock = threading.Lock()
        self.last_tel = 0.0
        self.last_out = {}

    def start(self, label):
        """Point the recorder at the folder for `label` (None stops recording)."""
        if not label:
            self.dir = None
            return
        d = ROOT / re.sub(r"[^A-Za-z0-9._-]+", "_", label).strip("_")
        d.mkdir(parents=True, exist_ok=True)
        self.dir = d

    def _append(self, name, obj):
        if not self.dir:
            return
        with self.lock, gzip.open(self.dir / name, "at", encoding="utf-8") as f:
            f.write(json.dumps(obj, separators=(",", ":")) + "\n")

    def feed(self, info, results):
        self._append("feed.jsonl.gz", {"t": time.time(), "info": info, "results": results})

    def telemetry_session(self, payload):
        self._append("telemetry.jsonl.gz", {"t": time.time(), "session": payload})

    def telemetry_cars(self, cars):
        now = time.time()
        if now - self.last_tel < TELEMETRY_EVERY:
            return
        self.last_tel = now
        keep = [f for f in cars if (f.get("scoring") or {}).get("class") in CLASSES]
        if keep:
            self._append("telemetry.jsonl.gz", {"t": now, "cars": keep})

    def output(self, name, data):
        now = time.time()
        if now - self.last_out.get(name, 0) < OUTPUT_EVERY:
            return
        self.last_out[name] = now
        self._append("outputs.jsonl.gz", {"t": now, "name": name, "data": data})


RECORDER = Recorder()
