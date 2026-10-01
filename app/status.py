"""Health snapshot for the local status page (http://localhost:8089, never public).

A background thread writes STATUS_DIR/status.json every WRITE_EVERY seconds, so the page
can tell "scraper alive but idle until the next session" apart from "scraper dead". The
rest of the code calls mark() when something succeeds; warnings and errors are kept in a
small in-memory buffer by a logging handler.
"""

import collections
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path

STATUS_DIR = Path(os.environ.get("STATUS_DIR", "/status"))
WRITE_EVERY = 15

STATE = {"started": time.time(), "ok": {}, "live": {}}
_problems = collections.deque(maxlen=40)


class _ProblemBuffer(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if record.exc_info and record.exc_info[1]:
            msg += f" ({type(record.exc_info[1]).__name__}: {record.exc_info[1]})"
        _problems.append({"t": record.created, "level": record.levelname, "logger": record.name, "msg": msg[:300]})


def mark(what, **info):
    """Record that `what` (points, history, schedule, feed, ...) just succeeded."""
    STATE["ok"][what] = {"t": time.time(), **info}


def live(**fields):
    STATE["live"].update(fields)


def _snapshot():
    import archive
    import live as live_mod
    tel = live_mod.TELEMETRY.snapshot()
    rec = archive.RECORDER.dir
    files = {p.name: p.stat().st_size for p in sorted(rec.iterdir())} if rec and rec.exists() else {}
    disk = shutil.disk_usage(archive.ROOT if archive.ROOT.exists() else "/")
    return {
        "now": time.time(),
        "started": STATE["started"],
        "ok": STATE["ok"],
        "live": STATE["live"],
        "telemetry": {"connected": tel["connected"], "last_data": tel["last_data"] or None,
                      "cars": len(tel["cars"]), "series": tel["session"].get("series_name_short"),
                      "session": tel["session"].get("session_name")},
        "recorder": {"dir": rec.name if rec else None, "files": files},
        "disk": {"free": disk.free, "total": disk.total},
        "problems": list(_problems)[::-1],
    }


def _writer():
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            tmp = STATUS_DIR / "status.json.tmp"
            tmp.write_text(json.dumps(_snapshot(), separators=(",", ":")))
            tmp.replace(STATUS_DIR / "status.json")
        except Exception:
            logging.getLogger("scraper.status").debug("status write failed", exc_info=True)
        time.sleep(WRITE_EVERY)


def start():
    h = _ProblemBuffer(level=logging.WARNING)
    logging.getLogger().addHandler(h)
    threading.Thread(target=_writer, name="status", daemon=True).start()
