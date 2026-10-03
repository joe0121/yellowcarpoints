"""Weather at the track right now, refreshed every few minutes during a race weekend (run by the analyst,
so the scraper's live timing is never held up). Written to wx_live.json; the slower forecast stays in
weather.json from the scraper.

- Open-Meteo "current" and 15-minute data for the track's own coordinates: temperature, rain falling,
  cloud, wind and gusts now, and rain expected over the next two hours in 15-minute steps (model values).
- The National Weather Service's latest observation from the nearest station to the track (measured,
  but the station is some kilometres away; its name and distance are kept).
- Radar (RainViewer): nearest rain, how the rain is moving, and when it could reach the track.
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
    try:
        doc["radar"] = radar(*ll)
    except Exception:
        log.exception("radar failed")
        doc["radar"] = old.get("radar")
    write("wx_live.json", doc)
    return True


# --- Radar nowcast (RainViewer, free, with attribution) ----------------------------------------------
# The forecast models miss pop-up storms; radar doesn't. Every refresh we read the newest radar frame and
# the one ~30 minutes before around the track (zoom 7, about 1 km a pixel, 3x3 tiles = ~380 km square),
# find the nearest rain, estimate how the rain field is moving from the shift between the two frames,
# and extrapolate: when (if at all, within 3 hours) rain would reach the track. Rough, and labelled so.
ZOOM, TILE, KMPX = 7, 256, None


def _tile_xy(lat, lon, z=ZOOM):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return x, y


def _frame(host, path, tx, ty):
    """Rain pixels around the track: {(px, py): level} with 1 light, 2 moderate, 3 heavy (by colour)."""
    from io import BytesIO
    from PIL import Image
    rain = {}
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            r = http.get(f"{host}{path}/256/{ZOOM}/{tx + i}/{ty + j}/2/1_0.png", timeout=30)
            if r.status_code != 200:
                continue
            im = Image.open(BytesIO(r.content)).convert("RGBA")
            px = im.load()
            for x in range(0, TILE, 2):          # every other pixel (2 km) is plenty
                for y in range(0, TILE, 2):
                    R, G, B, A = px[x, y]
                    if A < 150:
                        continue                  # transparent, or the faint clutter/drizzle shade
                    lvl = 3 if R > 190 and G < 110 else 2 if R > 190 else 1
                    rain[((i + 1) * TILE + x, (j + 1) * TILE + y)] = lvl
    return rain


def _shift(a, b, max_px=30, step=2):
    """(dx, dy) in pixels that best moves rain field a onto b (most overlapping rain pixels)."""
    sb, best = set(b), (0, 0, -1)
    pts = list(a)
    if len(pts) > 6000:
        pts = pts[::len(pts) // 6000 + 1]
    for dx in range(-max_px, max_px + 1, step):
        for dy in range(-max_px, max_px + 1, step):
            n = sum(1 for (x, y) in pts if (x + dx, y + dy) in sb)
            if n > best[2]:
                best = (dx, dy, n)
    return best[0], best[1], best[2] / max(1, len(pts))


def radar(lat, lon):
    maps = http.get("https://api.rainviewer.com/public/weather-maps.json", timeout=30).json()
    host, past = maps["host"], maps["radar"]["past"]
    if len(past) < 4:
        return None
    fx, fy = _tile_xy(lat, lon)
    tx, ty = int(fx), int(fy)
    cx, cy = (fx - tx + 1) * TILE, (fy - ty + 1) * TILE              # the track, in our 3x3 pixel grid
    kmpx = 40075 * math.cos(math.radians(lat)) / (2 ** ZOOM * TILE)
    now, before = past[-1], past[-4]                                  # frames are 10 minutes apart
    a, b = _frame(host, before["path"], tx, ty), _frame(host, now["path"], tx, ty)
    dt_h = (now["time"] - before["time"]) / 3600 or 0.5
    out = {"time": now["time"], "km_per_px": round(kmpx, 3), "tiles": {"z": ZOOM, "x": tx, "y": ty}, "host": host, "path": now["path"]}

    def polar(x, y):
        dx, dy = (x - cx) * kmpx, (y - cy) * kmpx
        return math.hypot(dx, dy), (math.degrees(math.atan2(dx, -dy)) + 360) % 360
    near = [(polar(x, y), lvl) for (x, y), lvl in b.items()]
    within = lambda km, lvl=1: sum(1 for (d, _), l in near if d <= km and l >= lvl)
    if near:
        (d, brg), lvl = min(near)
        out["nearest"] = {"km": round(d, 1), "bearing": round(brg), "level": lvl}
        heavy = [n for n in near if n[1] >= 2]
        if heavy:
            (hd, hb), hl = min(heavy)
            out["nearest_heavier"] = {"km": round(hd, 1), "bearing": round(hb), "level": hl}
    area = math.pi * (25 / kmpx) ** 2 / 4                              # pixels sampled every 2 px
    out["cover_25km"] = round(min(1, within(25) / area), 3)
    out["at_track"] = within(3) > 0
    # Motion of the rain field near the track (within ~120 km), then when rain would arrive.
    loc = lambda f: {p: l for p, l in f.items() if math.hypot(p[0] - cx, p[1] - cy) * kmpx <= 120}
    sx, sy, fit = _shift(loc(a), loc(b))
    vx, vy = sx * kmpx / dt_h, sy * kmpx / dt_h                         # km/h, east and south
    spd = math.hypot(vx, vy)
    out["motion"] = {"kmh": round(spd), "toward": round((math.degrees(math.atan2(vx, -vy)) + 360) % 360), "fit": round(fit, 2)}
    eta = None
    if spd >= 5 and fit >= 0.15:
        for (x, y), lvl in b.items():
            px_, py_ = (x - cx) * kmpx, (y - cy) * kmpx
            t = -(px_ * vx + py_ * vy) / (spd * spd)                    # hours to closest approach
            if 0 < t <= 3 and math.hypot(px_ + vx * t, py_ + vy * t) <= 4 and (eta is None or t < eta[0]):
                eta = (t, lvl)
    out["eta"] = eta and {"min": round(eta[0] * 60), "level": eta[1]}
    return out
