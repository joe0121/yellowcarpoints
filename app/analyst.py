"""Analyst: the Analysis tab's numbers, in their own container so the scraper never waits on them.

  - After qualifying: the pre-race prediction (fitted on every past WeatherTech race) and the caution
    history for this track. Redone when qualifying changes (re-runs, penalties to the order).
  - Race weekends: weather at the track every WX_LIVE_SECONDS (default 300), into wx_live.json.
  - During the race: every ANALYSIS_MINUTES (default 60) of race time, the in-race prediction from the
    live state (gaps, stops owed, recent pace), plus a history of the win odds for the chart.
It only reads what the scraper writes (live, laps, standings, quali, schedule) and writes predict.json
and insights.json. Past results are cached in CACHE_DIR, so Al Kamel's site is asked once per event.
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone

import cautions
import inrace
import predict
import wxlive
from common import now_iso, read, write

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("analyst")
EVERY = int(os.environ.get("ANALYSIS_MINUTES", "60")) * 60
WX_EVERY = int(os.environ.get("WX_LIVE_SECONDS", "300"))   # weather at the track, race weekends only


def secs(t):
    try:
        v = 0.0
        for p in str(t).split(":"):
            v = v * 60 + float(p)
        return v
    except ValueError:
        return None


def sig(obj):
    return hashlib.md5(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:10]


def race_session():
    """This weekend's race from the schedule: (start, end) as epoch seconds, or None."""
    for s in (read("schedule.json") or {}).get("sessions", []):
        if s.get("race"):
            return datetime.fromisoformat(s["start"]).timestamp(), datetime.fromisoformat(s["end"]).timestamp()
    return None


def tick(state):
    live, quali, standings = read("live.json") or {}, read("quali.json"), read("standings.json")
    event = (quali or {}).get("event") or live.get("event")
    if not event or not standings:
        return
    doc = read("predict.json") or {}
    if doc.get("event") != event:
        doc = {"event": event}
    racing = live.get("is_race") and live.get("event") == event and not live.get("finished") \
        and time.time() - datetime.fromisoformat(live["updated"]).timestamp() < 180

    # Caution history: once per track.
    ins = read("insights.json")
    if (not ins or ins.get("track") != event) and time.time() - state.get(("ins", event), 0) > 6 * 3600:
        state[("ins", event)] = time.time()      # one attempt per track every 6 h, success or not
        rs = race_session()
        h = cautions.history(event, standings["season"], (rs[1] - rs[0]) if rs else 9600)
        if h:
            h["updated"] = now_iso()
            write("insights.json", h)
            log.info("caution history for %s: %d races", event, len(h["years"]))

    # Pre-race: whenever qualifying (this weekend's order) changes, until the race starts.
    q_sig = sig((quali or {}).get("classes"))
    if not racing and not live.get("is_race") and quali and quali.get("event") == event and doc.get("quali_sig") != q_sig \
            and time.time() - state.get(("pre", q_sig), 0) > 1800:
        state[("pre", q_sig)] = time.time()      # at most every 30 min for the same qualifying order
        pre = predict.prerace(event, standings, quali)
        if pre:
            doc.update({"updated": now_iso(), "season": standings["season"], "quali_sig": q_sig, "mode": "pre-race",
                        "prerace": pre, "classes": pre["classes"], "as_of": None, "history": [], **{k: pre[k] for k in ("weights", "races_used", "backtest", "hours")}})
            doc["history"] = [{"elapsed": 0, "label": "Start", "win": {c: {x["car"]: x["win"] for x in v["cars"]} for c, v in pre["classes"].items()}}]
            write("predict.json", doc)

    # In race: every EVERY seconds of race time.
    if racing and doc.get("prerace"):
        el = secs(live.get("elapsed")) or 0
        slot = int(el // EVERY)
        if slot >= 1 and slot > (doc.get("as_of") or {}).get("slot", 0):
            cls = inrace.predict(live, read("laps.json"), standings, quali, doc["prerace"])
            if cls:
                label = f"{el / 3600:.0f} h" if EVERY % 3600 == 0 else f"{int(el // 3600)}:{int(el % 3600 // 60):02d}"
                doc.update({"updated": now_iso(), "mode": "in-race", "classes": cls,
                            "as_of": {"slot": slot, "elapsed": round(el), "remaining": live.get("remaining"), "label": label}})
                doc["history"] = [h for h in doc.get("history", []) if h["elapsed"] < el] + [
                    {"elapsed": round(el), "label": label, "win": {c: {x["car"]: x["win"] for x in v["cars"]} for c, v in cls.items()}}]
                write("predict.json", doc)
                log.info("in-race prediction at %s", label)


def main():
    state = {}
    log.info("analyst up: in-race every %d min", EVERY // 60)
    while True:
        try:
            tick(state)
        except Exception:
            log.exception("analysis failed")
        if time.time() >= state.get("wx_next", 0):
            state["wx_next"] = time.time() + WX_EVERY
            try:
                wxlive.refresh()
            except Exception:
                log.exception("track weather failed")
        time.sleep(60)


if __name__ == "__main__":
    main()
