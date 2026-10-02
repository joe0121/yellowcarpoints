"""Race control messages: penalties, incidents under review and decisions, pit lane and flags.

IMSA's live timing feeds don't carry them, but Al Kamel publishes the official log as
"25_FlagsAnalysisWithRCMessages" for every session (straight after it ends) and, in endurance races,
with each hourly results snapshot. We take the newest one for the current event, checked alongside
the sector times (every 5 minutes in a session window), and only download it when it changes.
"""

import json
import logging
import re
import time
from urllib.parse import quote, unquote

from common import http, now_iso, read, write

log = logging.getLogger("scraper.racecontrol")
RC_FILE = re.compile(r"/25_FlagsAnalysisWithRCMessages_[^/]*\.JSON$")
FAST_SECS = 15          # check interval once the log turns out to be updated often
FAST_IF_WITHIN = 600    # two updates this close together (or one file growing in place) = updated often
_seen = {"path": None, "size": None, "changes": [], "fast": False}


def fast():
    """True once the log has shown it's being updated often enough to be worth a 15 s check."""
    return _seen["fast"]


def _record(path, size):
    """Note an update; switch to fast checks if updates come quickly or the same file grows."""
    now = time.time()
    grew = path == _seen["path"] and size != _seen["size"]
    _seen["changes"] = (_seen["changes"] + [now])[-10:]
    quick = len(_seen["changes"]) > 1 and now - _seen["changes"][-2] < FAST_IF_WITHIN
    if (grew or quick) and not _seen["fast"]:
        log.info("race control log is updating often (%s): checking every %d s", "file grew in place" if grew else "updates <10 min apart", FAST_SECS)
    _seen.update(path=path, size=size, fast=_seen["fast"] or grew or quick)


def latest_log(page_html, series):
    """(file path, label) for the newest WeatherTech session's race control log; within a session
    the final file beats the hourly snapshots, and later hours beat earlier ones."""
    best = None
    for link in (unquote(h) for h in re.findall(r'href="([^"]+)"', page_html)):
        if f"_{series}/" not in link or not RC_FILE.search(link):
            continue
        m = re.search(rf"_{re.escape(series)}/(\d{{12}})_([^/]+)/(?:(\d+)_Hour (\d+)/)?", link)
        if not m:
            continue
        key = (m.group(1), 0 if m.group(3) else 1, int(m.group(4) or 0))
        if best is None or key > best[0]:
            best = (key, link, m.group(2) + (f" (to hour {m.group(4)})" if m.group(3) else ""))
    return best and (best[1], best[2])


def cars_in(text):
    """Car numbers a message is about: 'Car 11: ...', 'Car #6', 'CARS 2 & 16', 'cars 3, 4 and 13'."""
    cars = []
    for m in re.finditer(r"(?i)\bcars?\s*#?\s*((?:\d{1,3}[\s,&#]*(?:and\s+)?)+)", text):
        cars += re.findall(r"\d{1,3}", m.group(1))
    cars += re.findall(r"(?i)\bwith\s+#?(\d{1,3})\b", text)      # "Incident Responsibility with 73"
    return list(dict.fromkeys(cars))


def tag(text, rec_type):
    if rec_type != "RCMessage":
        return "flag"
    t = text.lower()
    if "penalt" in t and t.rstrip().endswith("warning"):
        return "warning"
    if "penalt" in t or "drive through" in t or "stop and go" in t or "stop + go" in t or "black flag" in t:
        return "penalty"
    if "under review" in t or "noted" in t or "under investigation" in t:
        return "review"
    if "no action" in t or "reviewed" in t or "warning" in t or "decision" in t or "rescinded" in t:
        return "decision"
    if "pit" in t and ("open" in t or "closed" in t):
        return "pit"
    if any(w in t for w in ("flag", "fcy", "full course", "safety car", "code 60", "wave by", "wave-by")):
        return "flag"
    return "info"


def secs(t):
    try:
        out = 0.0
        for part in str(t).split(":"):
            out = out * 60 + float(part)
        return round(out, 1)
    except ValueError:
        return None


def summarise(doc):
    msgs = []
    for f in doc.get("flags", []):
        text = (f.get("message") or "").strip() if f.get("rec_type") == "RCMessage" else (f.get("flag") or "").strip()
        if not text:
            continue
        msgs.append({"time": f.get("time"), "elapsed": secs(f.get("elapsed")), "lap": f.get("lap") or None,
                     "kind": tag(text, f.get("rec_type")), "text": text, "cars": cars_in(text)})
    s = doc.get("session", {})
    return {"session": s.get("session_name"), "event": s.get("event_name"),
            "note": (s.get("report_message") or "").strip() or None, "messages": msgs}


def refresh(base, page_html, series):
    """Update racecontrol.json if a newer log exists. Returns True when it changed."""
    found = latest_log(page_html, series)
    if not found:
        return False
    path, label = found
    size = http.head(base + quote(path), timeout=30).headers.get("Content-Length")
    old = read("racecontrol.json") or {}
    if old.get("path") == path and old.get("size") == size:
        if _seen["path"] is None:
            _seen.update(path=path, size=size)      # after a restart: known file, not a new update
        return False
    doc = json.loads(http.get(base + quote(path), timeout=60).content.decode("utf-8-sig"))
    _save(path, size, label, doc)
    return True


def _save(path, size, label, doc):
    out = summarise(doc)
    prev = _seen["changes"][-1] if _seen["changes"] else None
    write("racecontrol.json", {"updated": now_iso(), "label": label, "path": path, "size": size, **out})
    _record(path, size)
    # Logged with the gap since the last update, so after the weekend we know how often IMSA publishes it.
    log.info("race control: %s, %d messages (%s since the previous update)", label, len(out["messages"]),
             f"{(time.time() - prev) / 60:.0f} min" if prev else "first this run")


def quick_check(base):
    """Fast mode: has the known log file changed? A HEAD request; downloads only when it has."""
    path = _seen["path"]
    if not path:
        return False
    size = http.head(base + quote(path), timeout=15).headers.get("Content-Length")
    if size == _seen["size"]:
        return False
    old = read("racecontrol.json") or {}
    doc = json.loads(http.get(base + quote(path), timeout=60).content.decode("utf-8-sig"))
    _save(path, size, old.get("label"), doc)
    return True
