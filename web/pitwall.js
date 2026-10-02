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
function pwPace(lc, lapsCls, car) {
  const p = lc.strategy?.cars?.[car]?.pace;
  if (p) return p;
  const c = pwClean(lapsCls[car]).slice(-10).map(q => q[1]);
  return c.length >= 3 ? medianOf(c) : null;
}
function pwClassPace(lc, lapsCls) {
  if (lc.strategy?.class_pace) return lc.strategy.class_pace;
  const v = lc.cars.map(r => pwPace(lc, lapsCls, r.car)).filter(Boolean);
  return v.length ? medianOf(v) : null;
}
// Clean laps for pace: the stop is in lap s+1 and the out-lap is s+2 (stops are logged when the
// pit-stop count goes up, before the in-lap is complete), lap 1 and anything over 107% left out.
function pwClean(d) {
  if (!d?.laps?.length) return [];
  const pit = new Set((d.stops || []).flatMap(s => [s + 1, s + 2]));
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

// What a stop costs in this class: measured from this race's stops once there are enough, else the
// historical figure for this track, else the pit-lane time the scraper uses.
function pwPitLoss(lc, lapsCls, cls) {
  const flags = laps?.flags?.[cls] || [], rows = lc.cars;
  const leadLaps = Math.max(0, ...rows.map(r => +r.laps || 0));
  // Class lap time per lap number, from laps nobody pitted on (the yardstick for yellow stops).
  const byLap = {};
  for (const d of Object.values(lapsCls)) {
    const pit = new Set((d.stops || []).flatMap(s => [s + 1, s + 2]));
    for (const [n, t] of d.laps || []) if (n > 1 && !pit.has(n)) (byLap[n] ||= []).push(t);
  }
  const green = { all: [], fuel: [], full: [] }, fcy = [];
  for (const r of rows) {
    const d = lapsCls[r.car];
    if (!d?.stops?.length) continue;
    const L = new Map(d.laps), ref = medianOf(pwClean(d).map(q => q[1])), down = leadLaps - (+r.laps || 0);
    const tel = r.energy?.stops || [];
    for (const s of d.stops) {
      const a = L.get(s + 1), b = L.get(s + 2);
      if (!a || !b || s < 2) continue;
      const kind = pwFlagAt(flags, s + 1 + down), kind2 = pwFlagAt(flags, s + 2 + down);
      if (kind === "green" && kind2 === "green" && ref) {
        const loss = a + b - 2 * ref;
        if (loss < 20 || loss > 250) continue;
        green.all.push(loss);
        const t = tel.find(x => Math.abs(x.lap - s) <= 1);
        if (t) (t.tyres || t.driver_change ? green.full : green.fuel).push(loss);
      } else if (kind === "yellow" && kind2 === "yellow") {
        const y = [byLap[s + 1], byLap[s + 2]].map(v => v && v.length >= 3 ? medianOf(v) : null);
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

// Class order once everyone has made the stops they owe (server's owes_stop), using the measured loss.
function pwNet(lc, lapsCls, loss) {
  const pace = pwClassPace(lc, lapsCls), yellow = isYellow(live.flag), per = yellow && loss.fcy ? loss.fcy : loss.green;
  const rows = lc.cars.map(r => ({ r, gap: pwGap(r, pace), owes: r.owes_stop || 0 }))
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
    + tile(net.yellow ? "Net (if yellow holds)" : "Net position", `P${mine.pos}`, `P${me.class_pos} on track${mine.owes ? " · owes a stop" : ""}`, "big")
    + tile("Ahead on net", up ? `#${esc(up.r.car)}` : "—", up ? `${gapTxt(mine, up)} up the road${up.owes ? " · owes a stop" : ""}` : "leading on net")
    + tile("Behind on net", dn ? `#${esc(dn.r.car)}` : "—", dn ? `${gapTxt(dn, mine)} back${dn.owes ? " · owes a stop" : ""}` : "")
    + tile("Next stop", me.in_pit ? "in pit" : toStop != null ? (toStop <= 0 ? "due" : `${toStop} lap${toStop === 1 ? "" : "s"}`) : "–",
        e?.next_stop_lap ? `L${e.next_stop_lap}${e.eta_min != null ? ` · ~${e.eta_min} min` : ""}` : s?.typical ? `est. from stint lengths` : "")
    + tile("Energy", e ? `${Math.round(e.now)}%` : "–", e?.laps_left != null ? `${e.laps_left.toFixed(1)} laps on this tank` : "no telemetry")
    + tile("Driver", inCar ? esc(inCar.name.split(" ").at(-1)) : esc(me.driver || "–"),
        inCar ? `${me.drivers.stint_secs != null ? `stint ${hm(me.drivers.stint_secs)} · ` : ""}${inCar.short ? `needs ${hm(inCar.short)} more` : "minimum done"}` : "",
        drv && (drv.overbooked || ["impossible", "urgent"].includes(drv.worst)) ? "warn" : "")
    + tile("Stops to the flag", fin ? `${fin.stops}` : "–", fin ? `${up ? `#${esc(up.r.car)} ${stopsTxt(up)}` : ""}${up && dn ? " · " : ""}${dn ? `#${esc(dn.r.car)} ${stopsTxt(dn)}` : ""}${fin.measured ? "" : " · est."}` : "")
    + `</div><p class="pwline">${pwSituation(sel, me, mine, up, dn, net, loss, fin, drv, remaining, toStop)}</p>`;
}

// One plain sentence: the most pressing thing for the selected car right now.
function pwSituation(sel, me, mine, up, dn, net, loss, fin, drv, remaining, toStop) {
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
