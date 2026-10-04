// Header chip: countdown to the next WeatherTech session, or time left in the one running.
// Scheduled times come from IMSA's weekend schedule (data/schedule.json); while a session is
// live, time left comes from IMSA's live timing (data/live.json) so delays and red flags count.
(() => {
  const el = document.getElementById("countdown");
  if (!el) return;
  let sessions = [], live = null, calendar = [];

  const kind = n => /practice/i.test(n) ? "Practice" : /qualif/i.test(n) ? "Qualifying" : /warm/i.test(n) ? "Warm-up" : "Race";
  const label = n => n.replace(/ - WeatherTech Championship$/i, "").replace(/^WeatherTech Championship /i, "");
  const hms = t => { const p = String(t || "").split(":").map(Number); return p.length === 3 && p.every(x => !isNaN(x)) ? p[0] * 3600 + p[1] * 60 + p[2] : null; };

  function span(s) {
    s = Math.max(0, Math.round(s));
    const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60;
    if (d) return `${d} d ${h} h`;
    if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
    return `${m} min ${String(sec).padStart(2, "0")} s`;
  }

  async function load() {
    try {
      const [sch, lv, cal] = await Promise.all(["schedule", "live", "calendar"].map(n =>
        fetch(`data/${n}.json`, { cache: "no-cache" }).then(r => r.ok ? r.json() : null).catch(() => null)));
      sessions = (sch?.sessions || []).map(s => ({ ...s, t0: new Date(s.start) / 1e3, t1: new Date(s.end) / 1e3 }));
      live = lv;
      calendar = cal?.events || [];
    } catch (e) { /* keep what we had */ }
    tick();
  }

  function tick() {
    const now = Date.now() / 1e3;
    const cur = sessions.find(s => s.t0 <= now && now < s.t1 + 1800);
    const next = sessions.find(s => s.t0 > now);
    let text = null, state = "next";
    if (cur) {
      // Prefer the live feed's clock when it's fresh and still running.
      const age = live ? now - new Date(live.updated) / 1e3 : Infinity;
      const feedLeft = age < 180 && !live.finished ? hms(live.remaining) : null;
      if (live && age < 180 && live.finished) {
        // Over: count down to the next session if there is one, otherwise just say it's done.
        if (!next) { text = `${label(cur.name)} · finished`; state = "done"; }
      } else if (feedLeft != null) {
        text = `LIVE · ${label(cur.name)} · ${span(feedLeft - age)} left`; state = "live";
      } else if (now < cur.t1) {
        text = `LIVE · ${label(cur.name)} · about ${span(cur.t1 - now)} left`; state = "live";
      }
    }
    if (!text && next) {
      const when = new Date(next.t0 * 1e3).toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
      const name = label(next.name);
      text = `${name.startsWith(kind(next.name)) ? name : `${kind(next.name)}: ${name}`} in ${span(next.t0 - now)} · ${when}`;
    }
    // No weekend schedule up yet (IMSA posts session times about two weeks before an event): count down
    // to the next round on the season calendar instead, by its dates.
    if (!text && calendar.length) {
      const today = new Date().toISOString().slice(0, 10), ev = calendar.find(e => e.end >= today);
      if (ev) {
        const t0 = new Date(ev.start + "T00:00:00-05:00") / 1e3, fmt = d => new Date(d + "T12:00:00").toLocaleDateString([], { month: "short", day: "numeric" });
        const dates = `${fmt(ev.start)}–${fmt(ev.end).replace(/^[A-Za-z]+ /, ev.start.slice(5, 7) === ev.end.slice(5, 7) ? "" : "$&")}`;
        text = t0 > now ? `Next race: ${ev.name} in ${span(t0 - now)} · ${dates}` : `Race weekend: ${ev.name} · ${dates}`;
        el.title = "Session times appear here about two weeks before the event, when IMSA publishes the weekend schedule.";
      }
    }
    el.hidden = !text;
    el.dataset.state = state;
    el.textContent = text || "";
  }

  load();
  setInterval(load, 60e3);
  setInterval(tick, 1e3);
})();
