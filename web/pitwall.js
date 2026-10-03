// Pit wall: the numbers a strategist acts on, worked out in the page from live.json and laps.json
// every poll. Net position, what a stop costs (measured in this race, else a historical figure),
// where the car rejoins if it pits now, fuel to the flag and drive-time compliance.
// Uses the Race page's helpers ($, esc, lapTime, hmsSecs, hm, medianOf, live, laps).

// What a stop cost at Petit Le Mans 2021-2025 (Al Kamel time cards: in-lap + the lap with the stop,
// against the class's lap time at the same moment). Yellow stops are in seconds at yellow pace,
// which is what decides track position while the field is behind the safety car.
const PIT_PRIOR = {
  "Road Atlanta": { source: "Petit Le Mans 2021–25",
    GTP: { green: 75.5, fcy: 40.4 }, LMP2: { green: 74.6, fcy: 56.4 }, GTDPRO: { green: 75.0, fcy: 39.0 }, GTD: { green: 76.6, fcy: 45.3 } },
};
const isYellow = f => /yellow|fcy|caution|safety/i.test(f || "");
const pwClock = secsFromNow => new Date(Date.now() + secsFromNow * 1000).toLocaleTimeString([], { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });

// Class gap to the leader in seconds (laps down at the class pace).
function pwGap(r, pace) {
  if (r.class_pos === 1) return 0;
  const g = String(r.gap || "").trim(), m = g.match(/^-?(\d+) laps?/i);
  if (m) return +m[1] * (pace || 0);
  const v = secsOf(g);
  return v == null ? null : v;
}
const isRed = f => /red/i.test(f || "");
// Current pace: the car's last five green-flag laps, whatever the conditions (no 107% cut, so a wet
// restart or a car on the wrong tyres counts straight away); in- and out-laps and yellow/red laps left out.
function pwRecent(lc, lapsCls, car, n = 5) {
  const d = lapsCls[car], r = lc.cars.find(x => x.car === car);
  if (!d?.laps?.length || !r) return [];
  const flags = laps?.flags?.[lc.cls || ""] || laps?.flags?.[Object.keys(laps?.classes || {}).find(k => laps.classes[k] === lapsCls)] || [];
  const leadLaps = Math.max(0, ...lc.cars.map(x => +x.laps || 0)), down = leadLaps - (+r.laps || 0);
  const pit = new Set((d.stops || []).flatMap(s => [s, s + 1, s + 2]));
  const ok = d.laps.filter(([k, t]) => k > 1 && !pit.has(k) && pwFlagAt(flags, k + down) === "green" && t < 400);
  return ok.slice(-n);
}
function pwPace(lc, lapsCls, car) {
  const rec = pwRecent(lc, lapsCls, car).map(q => q[1]);
  if (rec.length >= 3) return medianOf(rec);
  const p = lc.strategy?.cars?.[car]?.pace;
  if (p) return p;
  const c = pwClean(lapsCls[car]).slice(-10).map(q => q[1]);
  return c.length >= 3 ? medianOf(c) : null;
}
function pwClassPace(lc, lapsCls) {
  const v = lc.cars.map(r => pwPace(lc, lapsCls, r.car)).filter(Boolean);
  return v.length ? medianOf(v) : lc.strategy?.class_pace || null;
}
// Clean laps for pace: a stop logged at lap s has its in-lap at s, the stop itself in s+1 and the
// out-lap s+2 (checked against the race's lap times); those, lap 1 and anything over 107% left out.
function pwClean(d) {
  if (!d?.laps?.length) return [];
  const pit = new Set((d.stops || []).flatMap(s => [s, s + 1, s + 2]));
  const l = d.laps.filter(([n]) => n > 1 && !pit.has(n));
  if (!l.length) return [];
  const best = Math.min(...l.map(q => q[1]));
  return l.filter(q => q[1] <= best * 1.07);
}
// Flag at a given car lap: the class's flag log is by leader lap, so shift by the laps the car is down.
function pwFlagAt(flags, leaderLap) {
  let k = "green";
  for (const [lap, kind] of flags || []) { if (lap <= leaderLap) k = kind; else break; }
  return k;
}

// What a stop costs in this class: in-lap + the lap with the stop, against the cars that didn't pit on
// those laps; measured from this race's stops once there are enough, else the
// historical figure for this track, else the pit-lane time the scraper uses.
function pwPitLoss(lc, lapsCls, cls) {
  const flags = laps?.flags?.[cls] || [], rows = lc.cars;
  const leadLaps = Math.max(0, ...rows.map(r => +r.laps || 0));
  // Class lap time per lap number, from laps nobody pitted on (the yardstick for yellow stops).
  const byLap = {};
  for (const d of Object.values(lapsCls)) {
    const pit = new Set((d.stops || []).flatMap(s => [s, s + 1, s + 2]));
    for (const [n, t] of d.laps || []) if (n > 1 && !pit.has(n)) (byLap[n] ||= []).push(t);
  }
  const green = { all: [], fuel: [], full: [] }, fcy = [];
  for (const r of rows) {
    const d = lapsCls[r.car];
    if (!d?.stops?.length) continue;
    const L = new Map(d.laps), ref = medianOf(pwClean(d).map(q => q[1])), down = leadLaps - (+r.laps || 0);
    const tel = r.energy?.stops || [];
    for (const s of d.stops) {
      // In-lap + the lap with the stop (same as the historical figures).
      const a = L.get(s), b = L.get(s + 1);
      if (!a || !b || s < 2) continue;
      const kind = pwFlagAt(flags, s + down), kind2 = pwFlagAt(flags, s + 1 + down);
      // Against the cars that didn't pit on those laps (cancels out a drying track or traffic), else
      // against this car's own median clean lap.
      const same = [byLap[s], byLap[s + 1]].map(v => v && v.length >= 3 ? medianOf(v) : null);
      if (kind === "green" && kind2 === "green" && (ref || (same[0] && same[1]))) {
        const loss = same[0] && same[1] ? a + b - same[0] - same[1] : a + b - 2 * ref;
        if (loss < 20 || loss > 250) continue;
        green.all.push(loss);
        const t = tel.find(x => Math.abs(x.lap - s) <= 1);
        if (t) (t.tyres || t.driver_change ? green.full : green.fuel).push(loss);
      } else if (kind === "yellow" && kind2 === "yellow") {
        const y = [byLap[s], byLap[s + 1]].map(v => v && v.length >= 3 ? medianOf(v) : null);
        if (y[0] && y[1]) { const loss = a + b - y[0] - y[1]; if (loss > 10 && loss < 250) fcy.push(loss); }
      }
    }
  }
  const prior = PIT_PRIOR[live?.event]?.[cls], src = PIT_PRIOR[live?.event]?.source;
  const med = v => v.length ? medianOf(v) : null;
  const out = {
    green: green.all.length >= 3 ? med(green.all) : prior?.green ?? lc.pit_loss ?? null,
    greenSrc: green.all.length >= 3 ? `measured, ${green.all.length} green stops this race` : prior ? `${src} (no green stops measured yet)` : lc.pit_loss ? "pit-lane time" : null,
    fcy: fcy.length >= 2 ? med(fcy) : prior?.fcy ?? null,
    fcySrc: fcy.length >= 2 ? `measured, ${fcy.length} yellow stops this race` : prior ? `${src}` : null,
    fuel: green.fuel.length >= 2 ? med(green.fuel) : null, full: green.full.length >= 2 ? med(green.full) : null,
    measured: green.all.length >= 3,
  };
  // Stop types: measured when we have both, else the pit-lane difference between them.
  const pt = lc.strategy?.pit_types;
  if (out.green && !(out.fuel && out.full) && pt?.fuel_only && pt?.full) {
    out.fuel = out.fuel ?? out.green - Math.max(0, (pt.full - pt.fuel_only) / 2);
    out.full = out.full ?? out.green + Math.max(0, (pt.full - pt.fuel_only) / 2);
    out.typeSrc = "split by the class's pit-lane times";
  }
  return out;
}

// Who owes a stop, by fuel: each car's refuelling still needed to reach the flag, in standard class tanks
// ((laps to go - laps left in its tank) / the class's median full-tank laps), against the car in its
// class that needs the least. In effect: laps of fuel in hand, compared on one yardstick. Tyre-only stops (wets to slicks) and stop timing don't fool it. Fractional: a car a few laps
// of fuel behind owes a fraction of a stop. Needs telemetry energy for at least half the class; otherwise
// the scraper's pit-cycle guess stays. Marks the rows (owe_frac, owes_stop, net_pos) for every card.
function pwFixNet(lc, lapsCls) {
  if (!live?.is_race || !lc?.cars?.length) return;
  const remaining = hmsSecs(live.remaining);
  if (remaining == null) return;
  // Same laps to go for every car (the class's current lap time), so only tank state and fuel use differ.
  const need = {}, pace = pwClassPace(lc, lapsCls);
  if (!pace) return;
  // One standard tank for the class (median of the cars' full-tank laps), so small differences in
  // per-lap fuel use (and wet laps using less) don't get multiplied over the whole race.
  const tanks = lc.cars.map(r => r.energy?.full_tank_laps).filter(Boolean);
  const tank = tanks.length ? medianOf(tanks) : null;
  if (!tank) return;
  for (const r of lc.cars) {
    const e = r.energy;
    if (!e?.full_tank_laps || e.laps_left == null) continue;
    const left = r.in_pit ? tank : e.laps_left;
    need[r.car] = Math.max(0, (remaining / pace - left) / tank);
  }
  if (Object.keys(need).length < lc.cars.length / 2) return;
  const least = Math.min(...Object.values(need));
  for (const r of lc.cars) {
    if (!(r.car in need)) continue;
    r.owe_frac = +(need[r.car] - least).toFixed(2);
    r.owes_stop = r.owe_frac >= 0.75 ? 1 : 0;      // a whole stop behind on fuel, not just a later cycle
    r.owe_by = "fuel";
  }
  const loss = pwPitLoss(lc, lapsCls, Object.keys(laps?.classes || {}).find(k => laps.classes[k] === lapsCls) || "");
  for (const x of pwNet(lc, lapsCls, loss).rows) x.r.net_pos = x.pos;
}

// Class order once everyone has made the stops they owe (by fuel when we can, else the scraper's guess).
function pwNet(lc, lapsCls, loss) {
  const pace = pwClassPace(lc, lapsCls), yellow = isYellow(live.flag), per = yellow && loss.fcy ? loss.fcy : loss.green;
  const rows = lc.cars.map(r => ({ r, gap: pwGap(r, pace), owes: r.owe_frac ?? (r.owes_stop || 0) }))
    .map(x => ({ ...x, net: x.gap == null ? 1e6 + x.r.class_pos : x.gap + x.owes * (per || 0) }))
    .sort((a, b) => a.net - b.net);
  rows.forEach((x, i) => x.pos = i + 1);
  return { rows, per, yellow, pace };
}

// Fuel to the flag: stops still needed, and the window for the last one.
function pwFinish(r, lc, lapsCls, remaining) {
  const pace = pwPace(lc, lapsCls, r.car) || pwClassPace(lc, lapsCls), lap = +r.laps || 0;
  if (!pace || remaining == null) return null;
  const toGo = remaining / pace;                 // laps until the flag at this pace
  const e = r.energy, s = r.stint;
  let left, tank, measured = true;
  if (e?.laps_left != null && e.full_tank_laps) { left = e.laps_left; tank = e.full_tank_laps; }
  else if (s?.typical) { left = Math.max(0, s.laps_to_typical ?? 0); tank = s.typical; measured = false; }
  else return null;
  if (r.in_pit) left = tank;                     // leaving on a full tank
  const out = { toGo, left, tank, measured, lap };
  if (toGo <= left) return { ...out, stops: 0, spare: left - toGo };
  const stops = Math.ceil((toGo - left) / tank);
  // Last stop: stop any earlier and the last tank can't reach the flag; with one stop to go, any later
  // and this tank runs dry.
  const lastFrom = Math.max(lap, lap + Math.ceil(toGo - tank));
  const fillFrac = stops === 1 ? (toGo - left) / tank : null;   // share of a tank the final fill needs
  return { ...out, stops, lastFrom, lastTo: stops === 1 ? lap + Math.floor(left) : null,
           fillFrac, fillSecs: fillFrac != null && e?.full_fill_secs ? Math.round(fillFrac * e.full_fill_secs) : null };
}

// Drive time: requirement per driver and the 4-hours-in-any-6 limit, approximately, from lap times
// between driver changes.
function pwDriveStints(d, now) {
  if (!d?.laps?.length) return [];
  let t = 0;
  const at = new Map();
  for (const [n, s] of d.laps) { t += s; at.set(n, t); }
  const changes = (d.ev || []).filter(e => e[1] === "d").sort((a, b) => a[0] - b[0]);
  const out = [];
  let who = changes[0]?.[2] || now, from = 0;
  for (const e of changes) { const end = at.get(e[0]) ?? from; out.push({ who, from, to: end }); who = e[3]; from = end; }
  out.push({ who, from, to: t, current: true });
  return out.filter(x => x.who && x.to > x.from);
}
function pwDrive(r, d, rules, cls, remaining) {
  const cr = rules?.classes?.[cls] || {}, list = r.drivers?.list || [];
  if (!rules || !list.length) return null;
  const stints = pwDriveStints(d, r.drivers.now), end = stints.at(-1)?.to || 0;
  const W = 6 * 3600;
  const people = list.map(x => {
    const need = x.rating === "Bronze" && cr.am_min ? cr.am_min : cr.min || 0;
    // Rounded up to the minute (never show "needs 0:00"); under 30 s counts as done.
    const raw = Math.max(0, need - x.secs), short = raw < 30 ? 0 : Math.ceil(raw / 60) * 60;
    // 4-in-6: drive time in the last 6 hours of laps (approximate: lap times between driver changes).
    const used6 = stints.filter(s => s.who === x.name).reduce((a, s) => a + Math.max(0, Math.min(s.to, end) - Math.max(s.from, end - W)), 0);
    return { ...x, need, short, used6, maxLeft: rules.max - x.secs, sixLeft: rules.max_in_6h - used6, inCar: x.name === r.drivers.now };
  });
  const owed = people.reduce((a, p) => a + p.short, 0);
  const margin = 4 * 60;   // a stop and a driver change
  const shortN = people.filter(p => p.short && !p.inCar).length;
  // Over-booked: the time the drivers still need (plus a driver change each) is more than the race has left.
  const overbooked = remaining != null && owed + shortN * margin > remaining;
  for (const p of people) {
    if (!p.short || remaining == null) continue;
    if (p.inCar) { p.risk = p.short > remaining ? "impossible" : "ok"; continue; }
    // Latest moment this driver can get in and still reach the minimum on their own.
    p.latest = remaining - p.short - margin;
    p.risk = p.latest < 0 ? "impossible" : p.latest < 45 * 60 ? "urgent" : p.latest < 120 * 60 ? "plan" : "ok";
  }
  const worst = overbooked ? "impossible" : ["impossible", "urgent", "plan"].find(k => people.some(p => p.risk === k))
    || (people.some(p => p.inCar && p.sixLeft < 30 * 60) ? "limit" : "ok");
  return { people, owed, worst, overbooked, cr };
}

// --- pit wall strip (top of the Race tab) --------------------------------------------------------
function renderPitWall(sel, lc, lapsCls) {
  const el = $("pw"), me = lc?.cars.find(r => r.car === sel.car);
  el.hidden = !(live?.is_race && me);
  if (el.hidden) return;
  const loss = pwPitLoss(lc, lapsCls, sel.class), net = pwNet(lc, lapsCls, loss), remaining = hmsSecs(live.remaining);
  const i = net.rows.findIndex(x => x.r.car === sel.car), mine = net.rows[i], up = net.rows[i - 1], dn = net.rows[i + 1];
  const fin = pwFinish(me, lc, lapsCls, remaining), drv = pwDrive(me, lapsCls[me.car], live.drive_rules, sel.class, remaining);
  const e = me.energy, s = me.stint, toStop = e?.next_stop_lap ? e.next_stop_lap - (+me.laps || 0) : s?.laps_to_typical;
  const tile = (k, v, sub = "", cls = "") => `<div class="pwt ${cls}"><span class="k">${k}</span><b>${v}</b><span class="s">${sub}</span></div>`;
  const gapTxt = (a, b) => a && b ? `${(Math.abs(a.net - b.net)).toFixed(1)} s` : "";
  const inCar = drv?.people.find(p => p.inCar);
  const stopsTxt = c => { const f = pwFinish(c.r, lc, lapsCls, remaining); return f ? `${f.stops}` : "–"; };
  el.innerHTML = `<div class="pwgrid">`
    + tile(net.yellow ? "Net (if yellow holds)" : "Net position", `P${mine.pos}`, `P${me.class_pos} on track${mine.owes >= 0.25 ? ` · owes ${mine.owes >= 0.75 ? "a stop" : `~${mine.owes.toFixed(1)} of a stop`} (fuel)` : ""}`, "big")
    + tile("Ahead on net", up ? `#${esc(up.r.car)}` : "—", up ? `${gapTxt(mine, up)} up the road${up.owes >= 0.5 ? " · owes a stop" : ""}` : "leading on net")
    + tile("Behind on net", dn ? `#${esc(dn.r.car)}` : "—", dn ? `${gapTxt(dn, mine)} back${dn.owes >= 0.5 ? " · owes a stop" : ""}` : "")
    + tile("Next stop", me.in_pit ? "in pit" : toStop != null ? (toStop <= 0 ? "due" : `${toStop} lap${toStop === 1 ? "" : "s"}`) : "–",
        e?.next_stop_lap ? `L${e.next_stop_lap}${e.eta_min != null ? ` · ~${e.eta_min} min` : ""}` : s?.typical ? `est. from stint lengths` : "")
    + tile("Energy", e ? `${Math.round(e.now)}%` : "–", e?.laps_left != null ? `${e.laps_left.toFixed(1)} laps on this tank` : "no telemetry")
    + tile("Driver", inCar ? esc(inCar.name.split(" ").at(-1)) : esc(me.driver || "–"),
        inCar ? `${me.drivers.stint_secs != null ? `stint ${hm(me.drivers.stint_secs)} · ` : ""}${inCar.short ? `needs ${hm(inCar.short)} more` : "minimum done"}` : "",
        drv && (drv.overbooked || ["impossible", "urgent"].includes(drv.worst)) ? "warn" : "")
    + tile("Stops to the flag", fin ? `${fin.stops}` : "–", fin ? `${up ? `#${esc(up.r.car)} ${stopsTxt(up)}` : ""}${up && dn ? " · " : ""}${dn ? `#${esc(dn.r.car)} ${stopsTxt(dn)}` : ""}${fin.measured ? "" : " · est."}` : "")
    + `</div><p class="pwline">${pwSituation(sel, me, mine, up, dn, net, loss, fin, drv, remaining, toStop)}</p>`
    + (overrides?.event === live.event && (overrides.notes?.[sel.class] || overrides.tyres?.[sel.car]) ? `<p class="pwline dim">${overrides.tyres?.[sel.car] ? `#${esc(sel.car)} on <b>${esc(overrides.tyres[sel.car])}</b>. ` : ""}${esc(overrides.notes?.[sel.class] || "")} <span class="dim">(noted by hand)</span></p>` : "");
}

// One plain sentence: the most pressing thing for the selected car right now.
function pwSituation(sel, me, mine, up, dn, net, loss, fin, drv, remaining, toStop) {
  if (isRed(live.flag)) return `<b>Red flag:</b> the running order is frozen and no work is allowed on the cars. Projections below assume racing resumes now at each car's latest green-flag pace${remaining != null ? `, with ${hm(remaining)} on the clock` : ""}; expect them to move once the first green laps after the restart come in.`;
  if (drv?.overbooked) {
    const who = drv.people.filter(p => p.short);
    return `⚠ Drive time: ${who.map(p => `<b>${esc(p.name.split(" ").at(-1))}</b> needs ${hm(p.short)}`).join(", ")}: ${hm(drv.owed)} in all, more than the ${hm(remaining)} left. Not everyone can reach their minimum.`;
  }
  const urgent = drv?.people.find(p => p.risk === "impossible" || p.risk === "urgent");
  if (urgent) return urgent.risk === "impossible"
    ? `⚠ <b>${esc(urgent.name)}</b> can't reach the ${hm(urgent.need)} minimum in the time left (needs ${hm(urgent.short)} more): check the drive-time plan.`
    : `⚠ <b>${esc(urgent.name)}</b> still needs ${hm(urgent.short)} to reach the minimum: must be in the car by about ${pwClock(urgent.latest)} ET.`;
  if (me.in_pit) return `#${esc(me.car)} is in the pit lane.`;
  if (net.yellow && loss.fcy && loss.green) return `<b>Yellow:</b> a stop now costs about ${Math.round(loss.fcy)} s against the field instead of about ${Math.round(loss.green)} s under green`
    + (toStop != null && toStop <= 15 ? `, and #${esc(me.car)} is due in ${toStop} laps anyway.` : ".") + ` Pits may be closed at first: check race control.`;
  if (fin && remaining != null && remaining < 3 * 3600) {
    if (fin.stops === 0) return `Fuel to the flag: #${esc(me.car)} can make it on this tank, about ${fin.spare.toFixed(1)} laps spare at this pace.`;
    if (fin.stops === 1) return `Fuel to the flag: one more stop, in the window <b>L${fin.lastFrom}–L${fin.lastTo}</b>`
      + (fin.fillFrac != null && fin.fillFrac < 0.6 ? ` (a short fill, about ${Math.round(fin.fillFrac * 100)}% of a tank${fin.fillSecs ? `, ~${fin.fillSecs} s` : ""}).` : ".");
    return `Fuel to the flag: ${fin.stops} more stops; the last one from about L${fin.lastFrom}.`;
  }
  const parts = [`Net P${mine.pos}`];
  if (up) parts.push(`${Math.abs(mine.net - up.net).toFixed(1)} s behind #${esc(up.r.car)} once stops even out`);
  if (dn) parts.push(`${Math.abs(dn.net - mine.net).toFixed(1)} s clear of #${esc(dn.r.car)}`);
  if (toStop != null) parts.push(toStop <= 0 ? "stop due now" : `next stop in about ${toStop} laps`);
  return parts.join(", ") + ".";
}

// --- If we pit now --------------------------------------------------------------------------------
let pnType = null;
function renderPitNow(sel, lc, lapsCls, clsName) {
  const card = $("pn-card"), me = lc?.cars.find(r => r.car === sel.car);
  card.hidden = !(live?.is_race && me);
  if (card.hidden) return;
  const loss = pwPitLoss(lc, lapsCls, sel.class), pace = pwClassPace(lc, lapsCls), yellow = isYellow(live.flag);
  $("pn-title").textContent = `If #${sel.car} pits now · ${clsName}`;
  if (isRed(live.flag)) {
    $("pn-types").innerHTML = "";
    $("pn-body").innerHTML = `<p class="pncaution"><b>Red flag:</b> pit lane closed and no work allowed until race control reopens it. Under the restart procedure the field is usually led out behind the safety car, so the first stop after a red costs about what a stop under yellow does (~${Math.round(loss.fcy || 40)} s) if it comes in that first full-course caution.</p>`;
    $("pn-note").textContent = "";
    return;
  }
  const types = [["fuel", "Fuel only"], ["full", "Fuel + tyres / driver"]];
  pnType ||= "full";
  // Fill time: pitting early means a shorter fill than a typical stop.
  const e = me.energy, typFill = medianOf(lc.cars.flatMap(r => r.energy?.refills || []).filter(f => f.to - f.from >= 40).map(f => f.secs));
  const fillNow = e?.full_fill_secs ? Math.round((100 - e.now) / 100 * e.full_fill_secs) : null;
  const fillAdj = fillNow != null && typFill ? fillNow - typFill : 0;
  const base = (yellow ? loss.fcy : null) ?? (pnType === "fuel" ? loss.fuel : loss.full) ?? loss.green;
  const others = lc.cars.filter(r => r.car !== sel.car).map(r => ({ r, g: pwGap(r, pace) })).filter(x => x.g != null).sort((a, b) => a.g - b.g);
  const myGap = pwGap(me, pace);
  const exit = (cost, label, src) => {
    if (cost == null || myGap == null) return `<div class="pnrow"><b>${label}</b><span class="dim">no pit-loss figure yet</span></div>`;
    const after = myGap + cost, ahead = others.filter(x => x.g < after), behind = others.filter(x => x.g >= after);
    const a = ahead.at(-1), b = behind[0], a2 = ahead.at(-2);
    const who = (x, d, side) => x ? `<span class="pncar">#${esc(x.r.car)} <span class="dim">${d.toFixed(1)} s ${side}${x.r.owes_stop ? " · owes a stop" : ""}</span></span>` : "";
    return `<div class="pnrow"><div class="pnhead"><b>${label}</b><span class="pnpos">rejoins P${ahead.length + 1}</span><span class="dim">costs ~${Math.round(cost)} s · ${esc(src)}</span></div>`
      + `<div class="pnaround">${a2 ? who(a2, after - a2.g, "ahead") : ""}${who(a, after - (a?.g ?? 0), "ahead")}<span class="pnme">#${esc(sel.car)}</span>${who(b, (b?.g ?? 0) - after, "behind")}</div></div>`;
  };
  const greenCost = ((pnType === "fuel" ? loss.fuel : loss.full) ?? loss.green);
  $("pn-types").innerHTML = types.map(([k, l]) => `<button type="button" aria-pressed="${pnType === k}" data-k="${k}">${l}</button>`).join("");
  $("pn-types").querySelectorAll("button").forEach(b => b.onclick = () => { pnType = b.dataset.k; renderPitNow(sel, lc, lapsCls, clsName); });
  $("pn-body").innerHTML = (yellow ? exit(loss.fcy, "Under this yellow", loss.fcySrc || "") : exit(greenCost != null ? greenCost + fillAdj : null, "Under green", loss.greenSrc || ""))
    + (!yellow && loss.fcy ? exit(loss.fcy, "If a yellow came out now", loss.fcySrc) : "")
    + pwCautionEffect(sel, lc, lapsCls, pace);
  $("pn-note").innerHTML = `Rejoin is in class order only: the other cars' gaps stay as they are while #${esc(sel.car)} is in the lane. `
    + (fillNow != null ? `Fill now: about ${fillNow} s${typFill ? ` (a typical fill this race is ${Math.round(typFill)} s, so ${fillAdj >= 0 ? "+" : "−"}${Math.abs(Math.round(fillAdj))} s against the stop figure)` : ""}. ` : "")
    + `A stop's cost = in-lap + the lap with the stop, against a normal lap (under yellow, against the field's yellow laps).`
    + (loss.typeSrc ? ` Fuel-only vs full service ${loss.typeSrc}.` : "") + ` Pits close at the start of a full-course yellow; race control says when they open.`;
}

// Would a full-course yellow now help or hurt us against the cars around us? Who's due to stop first.
function pwCautionEffect(sel, lc, lapsCls, pace) {
  if (isYellow(live.flag)) return "";
  const me = lc.cars.find(r => r.car === sel.car), due = r => r.energy?.next_stop_lap ? r.energy.next_stop_lap - (+r.laps || 0) : r.stint?.laps_to_typical ?? null;
  const mine = due(me);
  if (mine == null) return "";
  const myGap = pwGap(me, pace);
  const near = lc.cars.filter(r => r.car !== sel.car).map(r => ({ r, d: due(r), g: pwGap(r, pace) }))
    .filter(x => x.d != null && x.g != null && Math.abs(x.g - myGap) < 90).sort((a, b) => a.g - b.g);
  if (!near.length) return "";
  const later = near.filter(x => x.d > mine + 3), sooner = near.filter(x => x.d < mine - 3);
  const verdict = mine <= 12 && later.length >= sooner.length ? "would help" : sooner.length > later.length ? "would help them more than us" : "would be roughly neutral";
  return `<p class="pncaution"><b>A yellow now ${verdict}.</b> #${esc(sel.car)} is due in ${Math.max(0, mine)} laps; `
    + near.slice(0, 4).map(x => `#${esc(x.r.car)} in ${Math.max(0, x.d)}`).join(", ") + ` (cars within 90 s). A car due soon gets a cheap stop; one that just stopped gets nothing.</p>`;
}

// --- To the flag: fuel and stops for our cars and the cars around them -----------------------------
function renderFinish(sel, lc, lapsCls, cars, clsName) {
  const card = $("fin-card"), remaining = hmsSecs(live?.remaining);
  card.hidden = !(live?.is_race && lc && remaining != null);
  if (card.hidden) return;
  $("fin-title").textContent = `To the flag · ${clsName}`;
  const loss = pwPitLoss(lc, lapsCls, sel.class), net = pwNet(lc, lapsCls, loss);
  const i = net.rows.findIndex(x => x.r.car === sel.car);
  const show = [...new Set([...cars.map(c => c.car), ...net.rows.slice(Math.max(0, i - 2), i + 3).map(x => x.r.car)])];
  const rowsHtml = show.map(car => {
    const r = lc.cars.find(x => x.car === car); if (!r) return "";
    const f = pwFinish(r, lc, lapsCls, remaining);
    const what = !f ? "–" : f.stops === 0 ? `makes it · ${f.spare.toFixed(1)} laps spare` : f.stops === 1
      ? `1 stop · window L${f.lastFrom}–L${f.lastTo}${f.fillFrac != null && f.fillFrac < 0.6 ? ` · short fill ~${Math.round(f.fillFrac * 100)}%${f.fillSecs ? ` (${f.fillSecs} s)` : ""}` : ""}`
      : `${f.stops} stops · last from ~L${f.lastFrom}`;
    const n = net.rows.find(x => x.r.car === car);
    return `<tr class="${car === sel.car ? "me" : cars.some(c => c.car === car) ? "tracked" : ""}"><td>#${esc(car)}</td><td>P${r.class_pos}</td><td>${n ? "P" + n.pos : "–"}</td>`
      + `<td>${f ? f.toGo.toFixed(0) : "–"}</td><td>${f ? f.left.toFixed(1) : "–"}</td><td class="l">${what}${f && !f.measured ? ` <span class="tag est">est.</span>` : ""}</td></tr>`;
  }).join("");
  $("fin-table").innerHTML = `<thead><tr><th>Car</th><th>Track</th><th>Net</th><th title="Laps to the flag at this car's pace">Laps to go</th><th title="Laps left on the current tank">Tank</th><th class="l">Stops to the flag</th></tr></thead><tbody>${rowsHtml}</tbody>`;
  $("fin-note").innerHTML = `${(remaining / 3600).toFixed(1)} h to go. Laps to go at each car's recent pace; tank from IMSA telemetry energy use (measured) or, without telemetry, typical stint lengths (<span class="tag est">est.</span>). `
    + `A yellow stretches a tank (slower laps use less energy), so windows open later than this. The window for a single last stop: stop before it and the last tank can't reach the flag; after it, this tank runs dry.`;
}

// --- Strategy graph: lap time through the whole race, with what's coming ----------------------------
// Laps the class winner completed at Petit Le Mans 2018-2025 (Al Kamel time cards; LMP2 leaves out
// 2019's 201-lap result). The x-axis ends here until the race has run 20 minutes, then at the live
// projection (leader's laps + time left at the class pace).
const RACE_LAPS = { "Road Atlanta": { source: "Petit Le Mans 2018–25 average", GTP: 433, LMP2: 430, GTDPRO: 406, GTD: 399 } };
const WX_SHORT = { rain: "Rain", sun: "Sunset", night: "Dark", cool: "Cooling" };

function rollingTrend(clean, k = 9) {
  return clean.map((p, i) => [p[0], medianOf(clean.slice(Math.max(0, i - k + 1), i + 1).map(q => q[1]))]).slice(Math.min(3, clean.length));
}

function renderStratGraph(sel, lc, lapsCls, cars, clsName) {
  const card = $("sg-card"), el = $("sg-chart");
  card.hidden = !(live?.is_race && lc);
  if (card.hidden) return;
  $("sg-title").textContent = `Race strategy graph · ${clsName}`;
  const rows = lc.cars, leaderLap = Math.max(0, ...rows.map(r => +r.laps || 0));
  const pace = pwClassPace(lc, lapsCls), remaining = hmsSecs(live.remaining), elapsed = hmsSecs(live.elapsed);
  const avg = RACE_LAPS[live.event]?.[sel.class];
  const projEnd = pace && remaining != null ? leaderLap + remaining / pace : null;
  const useLive = projEnd && (elapsed ?? 0) >= 1200 || !avg;
  const xEnd = Math.ceil(useLive ? projEnd ?? leaderLap + 10 : avg);
  const W = Math.max(320, el.clientWidth || 900), phone = W < 640, H = phone ? 260 : 320;
  // Phone: from the current lap to two hours of racing ahead. Desktop: the whole race.
  const x0 = phone ? Math.max(0, leaderLap - 2) : 0;
  const x1 = phone ? Math.max(x0 + 20, Math.min(xEnd + 2, leaderLap + (pace ? 7200 / pace : 90))) : xEnd + 4;
  const m = { l: 46, r: phone ? 34 : 70, t: 34, b: 30 }, iw = W - m.l - m.r, ih = H - m.t - m.b;
  const x = n => m.l + (n - x0) / (x1 - x0) * iw;

  // Per car: laps, clean laps, trend, current pace, projected stops and finish.
  const series = cars.map(c => {
    const d = lapsCls[c.car], r = rows.find(q => q.car === c.car);
    if (!d || !r) return null;
    const clean = pwClean(d), trend = rollingTrend(clean), now = pwPace(lc, lapsCls, c.car) || trend.at(-1)?.[1];
    const lap = +r.laps || 0, finish = now && remaining != null ? lap + remaining / now : null;
    const e = r.energy, stops = [];
    let next = e?.next_stop_lap ?? (r.stint?.laps_to_typical != null ? lap + Math.max(0, r.stint.laps_to_typical) : null);
    const every = e?.full_tank_laps ? Math.floor(e.full_tank_laps) : r.stint?.typical;
    while (next && finish && next < finish - 1 && every && stops.length < 20) { stops.push(next); next += every; }
    return { ...c, d, r, clean, trend, now, lap, finish, stops, estStops: !e?.full_tank_laps };
  }).filter(Boolean);
  const vis = series.flatMap(s => s.clean.filter(([n]) => n >= x0 && n <= x1).map(q => q[1]));
  if (!vis.length) { el.innerHTML = `<p class="empty">The graph fills in after a few clean laps.</p>`; $("sg-legend").innerHTML = ""; return; }
  const sorted = [...vis].sort((a, b) => a - b);
  let lo = sorted[0] - 0.4, hi = sorted[Math.floor(0.95 * (sorted.length - 1))] + 0.8;
  if (hi - lo < 3) { const mid = (hi + lo) / 2; lo = mid - 1.5; hi = mid + 1.5; }
  const y = v => m.t + (1 - (Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo)) * ih;
  let g = "";

  // Background: past caution likelihood ahead of the leader, this race's yellows behind it.
  const ins = cauData && cauData.track === live.event ? cauData : null;
  if (ins && avg) {
    const overall = medianOf(ins.years.map(yy => yy.laps)), scale = avg / overall, B = 10;
    const nb = Math.ceil(overall / B);
    for (let i = 0; i < nb; i++) {
      const often = ins.years.filter(yy => yy.cautions.some(c => c.lap < (i + 1) * B && c.end_lap > i * B)).length / ins.years.length;
      const a = Math.max(leaderLap, i * B * scale), b = Math.min(x1, (i + 1) * B * scale);
      if (often > 0 && b > a && b > x0) g += `<rect x="${x(Math.max(a, x0))}" y="${m.t}" width="${x(b) - x(Math.max(a, x0))}" height="${ih}" fill="var(--flag-yellow)" opacity="${(0.03 + 0.2 * often).toFixed(2)}"><title>Laps ${Math.round(i * B * scale)}–${Math.round((i + 1) * B * scale)}: a caution in ${Math.round(often * ins.years.length)} of ${ins.years.length} past races</title></rect>`;
    }
  }
  for (const [a, b, kind] of flagBands(sel.class)) {
    if (b < x0 || a > x1) continue;
    g += `<rect x="${x(Math.max(a, x0))}" y="${m.t}" width="${Math.max(2, x(Math.min(b, x1)) - x(Math.max(a, x0)))}" height="${ih}" fill="${kind === "red" ? "var(--critical)" : "var(--flag-yellow)"}" opacity=".45"><title>${kind === "red" ? "Red flag" : "Full-course yellow"}, laps ${a}–${b}</title></rect>`;
  }
  // Grid: every 10 laps (labels every 50 on desktop, every 10 on a phone); every second on the y-axis.
  for (let n = Math.ceil(x0 / 10) * 10; n <= x1; n += 10) {
    g += `<line x1="${x(n)}" x2="${x(n)}" y1="${m.t}" y2="${m.t + ih}" stroke="var(--grid)"${n % 50 ? ' stroke-dasharray="2 4"' : ""}/>`;
    if (phone ? true : n % 50 === 0) g += `<text x="${x(n)}" y="${H - 10}" text-anchor="middle">${n}</text>`;
  }
  const step = hi - lo > 8 ? 2 : 1;
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) g += `<line x1="${m.l}" x2="${m.l + iw}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)"/><text x="${m.l - 6}" y="${y(v) + 4}" text-anchor="end">${lapTime(v)}</text>`;
  // Weather events at their estimated laps.
  const lapAt = lapEstimator(rows, lc);
  if (lapAt) for (const ev of wxEvents()) {
    const n = lapAt(ev.ts);
    if (n == null || n < x0 || n > x1) continue;
    g += `<line x1="${x(n)}" x2="${x(n)}" y1="${m.t - 4}" y2="${m.t + ih}" stroke="var(--text-3)" stroke-dasharray="1 3"/><text x="${x(n)}" y="${m.t - 8}" text-anchor="middle" class="sgwx"><title>${esc(ev.text)}${ev.sub ? " · " + esc(ev.sub) : ""}</title>${WX_SHORT[ev.kind] || esc(ev.text.split(" ")[0])}</text>`;
  }
  // Now, and the finish.
  g += `<line x1="${x(leaderLap)}" x2="${x(leaderLap)}" y1="${m.t - 4}" y2="${m.t + ih}" stroke="var(--text)" stroke-width="1.5"/><text x="${x(leaderLap) + 4}" y="${m.t + 12}" class="lbl">Now L${leaderLap}</text>`;
  if (xEnd >= x0 && xEnd <= x1) g += `<line x1="${x(xEnd)}" x2="${x(xEnd)}" y1="${m.t - 4}" y2="${m.t + ih}" stroke="var(--text)" stroke-width="2" stroke-dasharray="6 3"/><text x="${x(xEnd) - 4}" y="${m.t + 12}" text-anchor="end" class="lbl">🏁 ~L${xEnd}</text>`;
  // My car's window for a single last stop.
  const me = series.find(s => s.car === sel.car), fin = me && pwFinish(me.r, lc, lapsCls, remaining);
  if (fin?.stops === 1 && fin.lastTo >= fin.lastFrom) g += `<rect x="${x(Math.max(x0, fin.lastFrom))}" y="${m.t + ih - 10}" width="${Math.max(3, x(Math.min(x1, fin.lastTo)) - x(Math.max(x0, fin.lastFrom)))}" height="10" fill="var(--accent)" opacity=".5"><title>#${esc(sel.car)}'s window for its last stop: L${fin.lastFrom}–L${fin.lastTo}</title></rect>`;
  // Cars: lap dots, trend, projection at the current pace, stops (past filled, projected hollow), finish.
  for (const s of series) {
    const col = s.style.color, mine = s.car === sel.car;
    const pastPit = new Set((s.d.stops || []).flatMap(q => [q, q + 1, q + 2]));
    for (const [n, t] of s.d.laps) {
      if (n < x0 || n > x1 || n < 2) continue;
      if (t > hi) { if (!pastPit.has(n)) g += `<path d="M${x(n) - 3} ${m.t + 2}L${x(n) + 3} ${m.t + 2}L${x(n)} ${m.t + 7}Z" fill="${col}" opacity=".5"><title>#${esc(s.car)} L${n}: ${lapTime(t)} (off the scale)</title></path>`; continue; }
      if (!pastPit.has(n)) g += `<circle cx="${x(n)}" cy="${y(t)}" r="${mine ? 2 : 1.6}" fill="${col}" opacity="${mine ? .55 : .35}"/>`;
    }
    const tr = s.trend.filter(([n]) => n >= x0 && n <= x1);
    if (tr.length > 1) g += `<path d="M${tr.map(([n, t]) => `${x(n)} ${y(t)}`).join("L")}" fill="none" stroke="${col}" stroke-width="${mine ? 2.5 : 2}" stroke-dasharray="${s.style.dash}"/>`;
    if (s.now && s.finish) {
      const a = Math.max(s.lap, x0), b = Math.min(s.finish, x1);
      if (b > a) g += `<line x1="${x(a)}" x2="${x(b)}" y1="${y(s.now)}" y2="${y(s.now)}" stroke="${col}" stroke-width="${mine ? 2 : 1.5}" stroke-dasharray="3 4" opacity=".8"/>`;
      if (s.finish <= x1) g += `<rect x="${x(s.finish) - 3.5}" y="${y(s.now) - 3.5}" width="7" height="7" fill="${col}" stroke="var(--surface)" stroke-width="1.2"><title>#${esc(s.car)} finishes on about lap ${Math.floor(s.finish)} at ${lapTime(s.now)}</title></rect>`;
    }
    const lane = m.t + ih - 9;   // stops sit along the bottom edge
    for (const q of s.d.stops || []) if (q >= x0 && q <= x1) g += `<path d="M${x(q)} ${lane}l4 7h-8z" fill="${col}"><title>#${esc(s.car)} stopped (L${q})</title></path>`;
    for (const q of s.stops) if (q >= x0 && q <= x1) g += `<path d="M${x(q)} ${lane}l4 7h-8z" fill="var(--surface)" stroke="${col}" stroke-width="1.5"><title>#${esc(s.car)} projected stop ~L${q}${s.estStops ? " (estimated from stint lengths)" : ""}</title></path>`;
  }
  el.innerHTML = `<div class="tip"></div><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Lap times through the race with projected stops and finish">${g}<rect class="sghit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
  // Hover: every plotted car's lap time on that lap (or its projected pace ahead of now).
  const svg = el.querySelector("svg"), tip = el.querySelector(".tip");
  svg.querySelector(".sghit").onmousemove = ev => {
    const box = svg.getBoundingClientRect(), px = (ev.clientX - box.left) * W / box.width, n = Math.round(x0 + (px - m.l) / iw * (x1 - x0));
    const lines = series.map(s => { const t = new Map(s.d.laps).get(n);
      return `<span style="color:${s.style.color}">■</span> #${esc(s.car)} ${t ? lapTime(t) : n > s.lap && s.now && (!s.finish || n <= s.finish) ? `~${lapTime(s.now)} <span class="dim">projected</span>` : "–"}${s.stops.includes(n) ? " · projected stop" : ""}`; });
    tip.innerHTML = `<b>Lap ${n}</b><br>${lines.join("<br>")}`;
    tip.style.display = "block";
    tip.style.left = `${Math.min(ev.clientX - box.left + 12, box.width - 180)}px`;
    tip.style.top = `${ev.clientY - box.top + 12}px`;
  };
  svg.querySelector(".sghit").onmouseleave = () => { tip.style.display = "none"; };
  $("sg-legend").innerHTML = series.map(s => `<span>${swatchOf(s.style)}#${esc(s.car)} <span class="dim">${esc(s.role)}</span></span>`).join("")
    + `<span class="dim">dots: laps · line: trend (median of the last 9 clean laps) · dashed ahead: pace over the last 5 green-flag laps · ▲ stop, △ projected · ■ finish</span>`;
  $("sg-note").innerHTML = `${isRed(live.flag) ? "<b>Red flag:</b> the projection assumes racing resumes now. " : ""}${phone ? "From now to two hours ahead. " : ""}Finish at ~L${xEnd}: ${useLive ? "the leader's laps plus the time left at the class pace" : esc(RACE_LAPS[live.event]?.source || "")}. `
    + `Yellow bands behind "Now" are this race's yellows; ahead of it, the shading is how often past races here had a caution on those laps${ins ? ` (${ins.years[0].year}–${ins.years.at(-1).year})` : ""}. `
    + `Projected stops from each car's energy use${series.some(s => s.estStops) ? " (or typical stint lengths where there's no telemetry)" : ""}; weather at its estimated lap. Laps off the top of the scale (pit, yellow) are marked along the top.`;
}

// --- Radar in the Weather card (RainViewer tiles, loaded straight from RainViewer) -------------------
// A square centred on the track: the last half hour of radar (loops), rings at 10/25/50 km, nearby
// towns, and the nowcast from the analyst (nearest rain, how it's moving, when it could arrive).
const RADAR_PLACES = { "Road Atlanta": [["Gainesville", 34.298, -83.824], ["Atlanta", 33.749, -84.388], ["Athens", 33.951, -83.357], ["Lawrenceville", 33.956, -83.988], ["Commerce", 34.204, -83.457]] };
let radarFrames = null, radarAt = 0, radarTimer = null;
const compass16 = d => ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"][Math.round(d / 22.5) % 16];
const LEVEL = ["", "light rain", "moderate rain", "heavy rain / storms"];

function radarText(R) {
  if (!R) return "";
  const t = new Date(R.time * 1000).toLocaleTimeString([], { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
  const n = R.nearest, h = R.nearest_heavier, m = R.motion;
  const parts = [];
  if (R.at_track) parts.push(`<b class="wxrain">rain over the track</b>`);
  else if (n) parts.push(`nearest rain <b>${Math.round(n.km)} km ${compass16(n.bearing)}</b> (${LEVEL[n.level]})`);
  else parts.push("no rain within ~190 km");
  if (h && (!n || h.km > n.km + 3)) parts.push(`${LEVEL[h.level]} ${Math.round(h.km)} km ${compass16(h.bearing)}`);
  if (m && m.kmh >= 5 && m.fit >= 0.15) parts.push(`moving toward the ${compass16(m.toward)} at ~${m.kmh} km/h`);
  if (R.eta && !R.at_track) parts.push(`<b class="wxrain">could reach the track in ~${R.eta.min} min</b> (${LEVEL[R.eta.level]})`);
  else if (n && !R.at_track && m?.fit >= 0.15) parts.push("not heading for the track at the moment");
  return `<b>Radar ${t}:</b> ${parts.join(" · ")}`;
}

async function renderRadar() {
  const box = $("wx-radar"), R = wxLive?.radar;
  if (!box) return;
  box.hidden = !R;
  if (!R) return;
  $("wx-radar-text").innerHTML = radarText(R);
  // Frames for the loop: RainViewer's list, refreshed every 5 minutes (the newest from the analyst if that fails).
  if (!radarFrames || Date.now() - radarAt > 300e3) {
    radarAt = Date.now();
    try { const m = await (await fetch("https://api.rainviewer.com/public/weather-maps.json")).json(); radarFrames = { host: m.host, list: m.radar.past.slice(-4) }; }
    catch (e) { radarFrames = { host: R.host, list: [{ time: R.time, path: R.path }] }; }
  }
  const S = Math.min(box.clientWidth || 360, 420), kmpx = R.km_per_px, { z, x: tx, y: ty } = R.tiles;
  // Only rebuild (and restart the loop) when there's a new frame or the card changed size.
  const key = `${radarFrames.list.map(f => f.time).join(",")}|${S}|${live?.event}`;
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  const lat = wxLive.lat, lon = wxLive.lon, n = 2 ** z;
  const fx = (lon + 180) / 360 * n, fy = (1 - Math.log(Math.tan(lat * Math.PI / 180) + 1 / Math.cos(lat * Math.PI / 180)) / Math.PI) / 2 * n;
  const VIEW_KM = 130, scale = S / (VIEW_KM / kmpx);                 // screen px per tile px
  const toScreen = (la, lo) => { const X = (lo + 180) / 360 * n, Y = (1 - Math.log(Math.tan(la * Math.PI / 180) + 1 / Math.cos(la * Math.PI / 180)) / Math.PI) / 2 * n;
    return [S / 2 + (X - fx) * 256 * scale, S / 2 + (Y - fy) * 256 * scale]; };
  const tiles = f => [-1, 0, 1].flatMap(i => [-1, 0, 1].map(j => {
    const [l, t] = [S / 2 + (tx + i - fx) * 256 * scale, S / 2 + (ty + j - fy) * 256 * scale];
    return `<img src="${radarFrames.host}${f.path}/256/${z}/${tx + i}/${ty + j}/2/1_0.png" style="left:${l}px;top:${t}px;width:${256 * scale}px;height:${256 * scale}px" alt="">`; })).join("");
  const rings = [10, 25, 50].map(km => `<circle cx="${S / 2}" cy="${S / 2}" r="${km / kmpx * scale}" fill="none" stroke="var(--text-3)" stroke-dasharray="3 4"/><text x="${S / 2 + 4}" y="${S / 2 - km / kmpx * scale - 3}" class="rdl">${km} km</text>`).join("");
  const places = (RADAR_PLACES[live?.event] || []).map(([nm, la, lo]) => { const [a, b] = toScreen(la, lo);
    return a > 0 && a < S && b > 0 && b < S ? `<circle cx="${a}" cy="${b}" r="2.5" fill="var(--text-2)"/><text x="${a + 5}" y="${b + 4}" class="rdl">${nm}</text>` : ""; }).join("");
  box.querySelector(".rdmap").style.cssText = `width:${S}px;height:${S}px`;
  box.querySelector(".rdframes").innerHTML = radarFrames.list.map((f, i) => `<div class="rdframe" data-i="${i}" ${i === radarFrames.list.length - 1 ? "" : "hidden"}>${tiles(f)}</div>`).join("");
  box.querySelector("svg").setAttribute("viewBox", `0 0 ${S} ${S}`);
  box.querySelector("svg").innerHTML = rings + places + `<circle cx="${S / 2}" cy="${S / 2}" r="5" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/><text x="${S / 2 + 8}" y="${S / 2 + 16}" class="rdl rdtrack">Track</text>`;
  // Loop the last half hour (pauses on the newest frame).
  clearInterval(radarTimer);
  const frames = [...box.querySelectorAll(".rdframe")], stamp = box.querySelector(".rdtime");
  let k = frames.length - 1, hold = 0;
  const show = () => { frames.forEach((f, i) => f.hidden = i !== k); const t = radarFrames.list[k]?.time;
    stamp.textContent = t ? new Date(t * 1000).toLocaleTimeString([], { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" }) + (k === frames.length - 1 ? " (latest)" : "") : ""; };
  show();
  if (frames.length > 1) radarTimer = setInterval(() => { if (k === frames.length - 1 && hold++ < 3) return; hold = 0; k = (k + 1) % frames.length; show(); }, 700);
}

// --- Title-fight markers on charts ----------------------------------------------------------------
// After a redraw, every "#NN" on a chart or legend for a car still mathematically in its class's title
// fight gets an asterisk, and each legend says what it means. One pass instead of touching every chart.
function titleAlive(cls) {
  return new Set((standings?.classes?.[cls]?.standings || []).filter(s => s.alive).map(s => s.car));
}
function starTitleCars(cls, root = document) {
  const alive = titleAlive(cls);
  if (!alive.size) return;
  const re = /#(\d{1,3})(?![\d*])/g;
  const zones = root.querySelectorAll(".chart svg, .legend, #sg-legend, #wp-legend, #pred-odds");
  for (const z of zones) {
    let starred = false;
    const walk = document.createTreeWalker(z, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walk.nextNode()) nodes.push(walk.currentNode);
    for (const t of nodes) {
      if (t.parentElement?.closest("title, .titlenote")) continue;
      const v = t.nodeValue.replace(re, (m, n) => alive.has(n) ? (starred = true, `#${n}*`) : m);
      if (v !== t.nodeValue) t.nodeValue = v;
    }
    if (starred && !(z instanceof SVGElement) && !z.querySelector(".titlenote"))
      z.insertAdjacentHTML("beforeend", `<span class="titlenote dim">* still in the title fight</span>`);
  }
}
