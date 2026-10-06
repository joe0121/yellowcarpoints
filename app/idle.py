"""Off-season / between-rounds idling. When the next WeatherTech round starts more than IDLE_DAYS away, the
scraper and analyst stop polling everything except a once-a-day check (calendar, points, titles) and wake up
IDLE_DAYS before the round. Driven by calendar.json; with no calendar the services never idle.

IDLE_DAYS=0 turns idling off.
"""

import os
from datetime import date, datetime, timedelta, timezone

from common import read

IDLE_DAYS = int(os.environ.get("IDLE_DAYS", "7"))
DAILY = 86400


def next_round(today=None):
    """The next round that hasn't finished yet, or None."""
    today = (today or date.today()).isoformat()
    events = (read("calendar.json") or {}).get("events") or []
    return next((e for e in sorted(events, key=lambda e: e["start"]) if e.get("end", e["start"]) >= today), None)


def wake_at(today=None):
    """When to wake up (UTC midnight, IDLE_DAYS before the next round), or None if we should be running."""
    if IDLE_DAYS <= 0:
        return None
    ev = next_round(today)
    if not ev:
        return None
    wake = datetime.fromisoformat(ev["start"]).replace(tzinfo=timezone.utc) - timedelta(days=IDLE_DAYS)
    return wake if datetime.now(timezone.utc) < wake else None


def describe():
    w, ev = wake_at(), next_round()
    return f"idle until {w:%Y-%m-%d} ({IDLE_DAYS} days before {ev['name']} {ev['start']})" if w else "active"
