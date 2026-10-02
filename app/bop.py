"""GTD / GTD PRO energy figures from IMSA's event Balance of Performance bulletin.

GTD cars run a virtual energy tank: each make gets a maximum stint energy (MJ) and the tank is
refilled at a fixed rate (MJ/s) while the fuel probe is connected. Both are in the event BoP
technical bulletin (a PDF on imsa.com), so a refill's duration is exact: energy to add / rate.
For 2026 every make's rate works out to a 40 s full refill.

Checked only around a race weekend (see refresh()). We find the newest "TB-IWSC-<yy>-<n>-<Event>-Event-BoP" bulletin on IMSA's technical bulletins
page, read the GTD table, and key each row by the car model so feed vehicle names can be matched.
"""

import io
import logging
import re
from datetime import datetime, timedelta, timezone

import pdfplumber

from common import http, now_iso, read, write

log = logging.getLogger("scraper.bop")
BULLETINS = "https://www.imsa.com/competitors/{year}-technical-bulletins/"
BOP_PDF = re.compile(r'href="([^"]*/TB-IWSC-\d\d-(\d+)-([^"/]*?)-Event-BoP-(\d{8})\.pdf)"', re.I)

# Model keywords, matched against both the bulletin rows and the timing feed's vehicle names.
MODELS = {
    "corvette": "Corvette Z06 GT3.R", "m4": "BMW M4 GT3", "296": "Ferrari 296 GT3", "mustang": "Ford Mustang GT3",
    "huracan": "Lamborghini Huracan GT3", "temerario": "Lamborghini Temerario GT3", "rcf": "Lexus RC F GT3",
    "720s": "McLaren 720S GT3", "amg": "Mercedes-AMG GT3", "911": "Porsche 911 GT3 R", "vantage": "Aston Martin Vantage GT3",
}
ALIASES = {"astonmartin": "vantage", "mercedes": "amg"}


def model_key(text):
    """Model keyword for a bulletin row or a feed vehicle name ('Chevrolet Corvette Z06 GT3.R' -> 'corvette')."""
    t = re.sub(r"[^a-z0-9]", "", (text or "").lower())
    for k in MODELS:
        if k in t:
            return k
    for alias, k in ALIASES.items():
        if alias in t:
            return k
    return None


def parse(pdf_bytes):
    """{model key: {energy_mj, rate_mj_s, full_fill_secs}} from the bulletin's GTD table."""
    out = {}
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "GTD" not in text or "Stint" not in text:
                continue
            lines = text.split("\n")
            for i, line in enumerate(lines):
                # Rows end with "<stint energy MJ> <replenishment MJ/s>" (notes may follow).
                m = re.search(r"\b(\d{3,4}) (\d{2}\.\d{3})\b", line)
                if not m:
                    continue
                # Model names wrap onto the lines either side, so look there if this line has none.
                key = model_key(line[:m.start()]) or model_key(lines[i - 1] if i else "") or \
                    model_key(lines[i + 1] if i + 1 < len(lines) else "")
                if key and key not in out:
                    energy, rate = int(m.group(1)), float(m.group(2))
                    out[key] = {"model": MODELS[key], "energy_mj": energy, "rate_mj_s": rate,
                                "full_fill_secs": round(energy / rate, 2)}
    return out


def refresh():
    """Update bop.json from the newest event BoP bulletin. Returns True when it changed."""
    old = read("bop.json") or {}
    now = datetime.now(timezone.utc)
    # BoP is set race by race and published ahead of the event: only look around a race weekend
    # (from 4 days before the first scheduled session to the last session's end), at most every
    # 12 hours there to catch a revised bulletin, plus once if we have none at all.
    if old:
        sessions = (read("schedule.json") or {}).get("sessions", [])
        starts = [datetime.fromisoformat(x["start"]) for x in sessions]
        ends = [datetime.fromisoformat(x["end"]) for x in sessions]
        weekend = bool(starts) and min(starts) - timedelta(days=4) <= now <= max(ends)
        if not weekend or now.timestamp() - old.get("checked", 0) < 12 * 3600:
            return False
    year = datetime.now(timezone.utc).year
    html = http.get(BULLETINS.format(year=year), timeout=30).text
    found = sorted(BOP_PDF.findall(html), key=lambda m: (m[3][4:] + m[3][:4], int(m[1])))   # by date, then number
    if not found:
        return False
    href, number, event, date = found[-1]
    url = href if href.startswith("http") else "https://www.imsa.com" + href
    if old.get("url") == url:
        write("bop.json", {**old, "checked": datetime.now(timezone.utc).timestamp()})
        return False
    cars = parse(http.get(url, timeout=60).content)
    if len(cars) < 5:
        log.warning("BoP bulletin %s: only %d GTD rows parsed, keeping the previous one", url, len(cars))
        return False
    write("bop.json", {"updated": now_iso(), "checked": datetime.now(timezone.utc).timestamp(), "url": url, "bulletin": f"TB-IWSC-{year % 100}-{number}",
                       "event": event.replace("-", " "), "date": f"{date[:2]}/{date[2:4]}/{date[4:]}", "models": cars})
    log.info("BoP: %s (%s), %d GTD models", event, url.rsplit("/", 1)[-1], len(cars))
    return True
