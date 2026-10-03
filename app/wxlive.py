"""Weather at the track right now, refreshed every few minutes during a race weekend (run by the analyst,
so the scraper's live timing is never held up). Written to wx_live.json; the slower forecast stays in
weather.json from the scraper.

- Open-Meteo "current" and 15-minute data for the track's own coordinates: temperature, rain falling,
  cloud, wind and gusts now, and rain expected over the next two hours in 15-minute steps (model values).
- The National Weather Service's latest observation from the nearest station to the track (measured,
  but the station is some kilometres away; its name and distance are kept).
"""

import logging
import math
from datetime import datetime, timezone

from common import http, now_iso, read, write
from weather import TRACKS, UA, in_weekend

log = logging.getLogger("analyst.wxlive")
# Stations near a track that the weather service doesn't list for the track's own grid square.
EXTRA_STATIONS = {"Road Atlanta": ["KGVL"]}     # Gainesville (Lee Gilmer), ~14 km north


def _km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def _open_meteo(lat, lon):
    d = http.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": lat, "longitude": lon, "timezone": "UTC", "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "precipitation_unit": "inch", "forecast_minutely_15": 8, "past_minutely_15": 2,
        "current": "temperature_2m,apparent_temperature,precipitation,rain,showers,weather_code,cloud_cover,wind_speed_10m,wind_direction_10m,wind_gusts_10m,relative_humidity_2m",
        "minutely_15": "precipitation,rain,weather_code"}, timeout=30).json()
    c, q = d["current"], d.get("minutely_15") or {}
    return ({"t": c["time"] + "Z", "f": c["temperature_2m"], "feels": c.get("apparent_temperature"), "rh": c.get("relative_humidity_2m"),
             "rain_in": c.get("precipitation"), "code": c.get("weather_code"), "cloud": c.get("cloud_cover"),
             "wind": c.get("wind_speed_10m"), "gust": c.get("wind_gusts_10m"), "dir": c.get("wind_direction_10m")},
            [{"t": t + "Z", "in": q["precipitation"][i], "code": q["weather_code"][i]} for i, t in enumerate(q.get("time", []))])


def _nws_obs(lat, lon, old):
    st = old.get("station")
    if not st:
        stations = http.get(f"https://api.weather.gov/points/{lat},{lon}", headers=UA, timeout=30).json()["properties"]["observationStations"]
        feats = http.get(stations, headers=UA, params={"limit": 50}, timeout=30).json()["features"]
        for sid in next((v for k, v in EXTRA_STATIONS.items() if k.lower() in (read("live.json") or {}).get("event", "").lower()), []):
            try:
                feats.append(http.get(f"https://api.weather.gov/stations/{sid}", headers=UA, timeout=30).json())
            except Exception:
                log.exception("station %s", sid)
        best = min(feats, key=lambda f: _km((lat, lon), (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0])))
        g = best["geometry"]["coordinates"]
        st = {"id": best["properties"]["stationIdentifier"], "name": best["properties"]["name"], "km": round(_km((lat, lon), (g[1], g[0])), 1)}
    p = http.get(f"https://api.weather.gov/stations/{st['id']}/observations/latest", headers=UA, timeout=30).json()["properties"]
    v = lambda k: (p.get(k) or {}).get("value")
    c2f = lambda c: None if c is None else round(c * 9 / 5 + 32, 1)
    kmh2mph = lambda k: None if k is None else round(k / 1.609, 1)
    return st, {"t": p.get("timestamp"), "text": p.get("textDescription"), "f": c2f(v("temperature")), "wind": kmh2mph(v("windSpeed")),
                "gust": kmh2mph(v("windGust")), "dir": v("windDirection"), "rh": v("relativeHumidity") and round(v("relativeHumidity")),
                "rain_last_hour_mm": v("precipitationLastHour")}


def refresh():
    """Returns True when it ran (a race weekend at a track we know)."""
    event = (read("live.json") or {}).get("event") or ""
    ll = next((v for k, v in TRACKS.items() if k.lower() in event.lower()), None)
    if not ll or not in_weekend():
        return False
    old = read("wx_live.json") or {}
    doc = {"updated": now_iso(), "place": event, "lat": ll[0], "lon": ll[1], "station": old.get("station")}
    try:
        doc["now"], doc["next15"] = _open_meteo(*ll)
    except Exception:
        log.exception("Open-Meteo current failed")
        doc["now"], doc["next15"] = old.get("now"), old.get("next15")
    try:
        doc["station"], doc["obs"] = _nws_obs(*ll, old)
    except Exception:
        log.exception("NWS observation failed")
        doc["obs"] = old.get("obs")
    write("wx_live.json", doc)
    return True
