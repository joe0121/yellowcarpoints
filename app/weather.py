"""Weather for the Race page: forecast for the track and IMSA's own track weather.

- National Weather Service hourly forecast (api.weather.gov, no key): temperature, chance of rain,
  wind, sky. Official, US only.
- Open-Meteo (free for non-commercial use, credited on the site): a second opinion on rain, plus
  15-minute precipitation, cloud cover and sunrise/sunset.
- IMSA's track weather station (Al Kamel's "26_Weather" file per session, hourly in long races):
  air and track temperature and wind, used for "now" and for pace vs track temperature.

Forecasts are fetched every 30 minutes from a few days before a race weekend until it ends; the
track weather is checked with the sector times (every 5 minutes in a session).
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

from common import http, now_iso, read, write

log = logging.getLogger("scraper.weather")
TRACKS = {"Road Atlanta": (34.1465, -83.8165)}     # event name (as in the entry list / live timing) -> lat, lon
UA = {"User-Agent": "yellowcarpoints.win weather (https://yellowcarpoints.win)"}
WX_FILE = re.compile(r"/26_Weather_[^/]*\.JSON$")


def _place():
    event = (read("entries.json") or {}).get("event") or (read("live.json") or {}).get("event") or ""
    for name, ll in TRACKS.items():
        if name.lower() in event.lower():
            return name, ll
    return None, None


def in_weekend():
    """From 3 days before the weekend's first session until its last one ends."""
    sessions = (read("schedule.json") or {}).get("sessions", [])
    if not sessions:
        return False
    now = datetime.now(timezone.utc)
    start = min(datetime.fromisoformat(s["start"]) for s in sessions)
    end = max(datetime.fromisoformat(s["end"]) for s in sessions)
    return start - timedelta(days=3) <= now <= end + timedelta(hours=1)


def _nws(lat, lon, old):
    points = old.get("nws_url")
    if not points:
        points = http.get(f"https://api.weather.gov/points/{lat},{lon}", headers=UA, timeout=30).json()["properties"]["forecastHourly"]
    periods = http.get(points, headers=UA, timeout=30).json()["properties"]["periods"]
    return points, [{"t": p["startTime"], "f": p["temperature"], "rain": (p.get("probabilityOfPrecipitation") or {}).get("value") or 0,
                     "wind": p.get("windSpeed"), "dir": p.get("windDirection"), "sky": p.get("shortForecast"), "day": p.get("isDaytime")}
                    for p in periods[:60]]


def _open_meteo(lat, lon):
    d = http.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon, "timezone": "UTC", "forecast_days": 3, "temperature_unit": "fahrenheit",
        "hourly": "temperature_2m,precipitation_probability,precipitation,cloud_cover,wind_speed_10m,is_day",
        "minutely_15": "precipitation", "daily": "sunrise,sunset"}, timeout=30).json()
    h, q, day = d["hourly"], d["minutely_15"], d["daily"]
    hourly = [{"t": t + "Z", "f": h["temperature_2m"][i], "rain": h["precipitation_probability"][i], "mm": h["precipitation"][i],
               "cloud": h["cloud_cover"][i], "day": bool(h["is_day"][i])} for i, t in enumerate(h["time"])]
    q15 = [{"t": t + "Z", "mm": q["precipitation"][i]} for i, t in enumerate(q["time"]) if q["precipitation"][i]]
    # Darkness: civil dusk, about 26 minutes after sunset at this latitude in autumn.
    sun = [{"date": dt, "sunrise": sr + "Z", "sunset": ss + "Z",
            "dusk": (datetime.fromisoformat(ss) + timedelta(minutes=26)).isoformat() + "Z"}
           for dt, sr, ss in zip(day["time"], day["sunrise"], day["sunset"])]
    return hourly, q15, sun


def refresh_forecast():
    """Update the forecast part of weather.json. Returns True when it ran."""
    name, ll = _place()
    if not ll:
        return False
    old = read("weather.json") or {}
    doc = {**old, "updated": now_iso(), "place": name}
    try:
        doc["nws_url"], doc["nws"] = _nws(*ll, old)
    except Exception:
        log.exception("NWS forecast failed")
    try:
        doc["om"], doc["rain15"], doc["sun"] = _open_meteo(*ll)
    except Exception:
        log.exception("Open-Meteo forecast failed")
    write("weather.json", doc)
    return True


def refresh_observed(base, page_html, series):
    """IMSA's track weather for the newest WeatherTech session (final file beats hourly snapshots)."""
    best = None
    for link in (unquote(h) for h in re.findall(r'href="([^"]+)"', page_html)):
        if f"_{series}/" not in link or not WX_FILE.search(link):
            continue
        m = re.search(rf"_{re.escape(series)}/(\d{{12}})_([^/]+)/(?:(\d+)_Hour (\d+)/)?", link)
        if m:
            key = (m.group(1), 0 if m.group(3) else 1, int(m.group(4) or 0))
            if best is None or key > best[0]:
                best = (key, link, m.group(2))
    if not best:
        return False
    _, path, session = best
    size = http.head(base + quote(path), timeout=30).headers.get("Content-Length")
    doc = read("weather.json") or {}
    obs = doc.get("obs") or {}
    if obs.get("path") == path and obs.get("size") == size:
        return False
    d = json.loads(http.get(base + quote(path), timeout=60).content.decode("utf-8-sig"))
    samples = [[s["time_utc_secconds"], s.get("air_temp"), s.get("track_temp"), s.get("wind_speed")] for s in d.get("meteoSamples", [])]
    doc["obs"] = {"session": session, "path": path, "size": size, "samples": samples}
    write("weather.json", doc)
    log.info("track weather: %s, %d samples", session, len(samples))
    return True
