// Car picker shared by the Championship and Race tabs: the Pratt Miller Motorsports cars, the other
// cars we follow (both from data/config.json), and "This is my car", a list of every car in every
// class. Any car picked becomes the site's "our car" on both tabs.
(() => {
  const CLASS_ORDER = ["GTP", "LMP2", "GTDPRO", "GTD"];
  const NAMES = { GTP: "GTP", LMP2: "LMP2", GTDPRO: "GTD PRO", GTD: "GTD" };
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // Every car we know about: championship standings (all classes), this weekend's entries, live timing.
  window.allCars = ({ standings, entries, live }) => {
    const out = new Map();
    for (const [cls, c] of Object.entries(standings?.classes || {}))
      for (const s of c.standings || []) out.set(s.car, { car: s.car, class: cls, team: s.team, pos: s.pos });
    for (const [car, e] of Object.entries(entries?.cars || {}))
      if (!out.has(car)) out.set(car, { car, class: e.class, team: e.team, pos: null });
    for (const [cls, c] of Object.entries(live?.classes || {}))
      for (const r of c.cars || []) if (!out.has(r.car)) out.set(r.car, { car: r.car, class: cls, team: r.vehicle, pos: null });
    return out;
  };
  // The selected car: from the address (#99), else the one saved in this browser, else the first followed car.
  window.pickCar = (data, store) => {
    const all = window.allCars(data), want = location.hash.slice(1) || store.get("car");
    const followed = data.standings?.cars || [];
    return followed.find(c => c.car === want) || all.get(want) || followed[0];
  };
  // --- friendly rivalry -------------------------------------------------------------------------
  // Friends: the cars we follow (Pratt Miller, Cadillac, AO Racing) and any other Corvette or Cadillac.
  window.isFriend = (car, data) => {
    if ((data.config?.groups || []).some(g => g.cars.includes(car))) return true;
    return /corvette|cadillac/i.test(data.entries?.cars?.[car]?.vehicle || "");
  };
  // "Porsche", "BMW", "Aston Martin"... (LMP2 cars are all ORECAs, so the team name there).
  window.makeOf = (car, data) => {
    const e = data.entries?.cars?.[car], v = e?.vehicle || "";
    if (!v || /^oreca/i.test(v)) return e?.team || `#${car}`;
    return /^aston/i.test(v) ? "Aston Martin" : v.split(" ")[0];
  };
  // Public enemy #1: the rival (not a friend) closest to our car in the championship.
  window.publicEnemy = (sel, data) => {
    const st = data.standings?.classes?.[sel.class]?.standings || [], me = st.find(s => s.car === sel.car);
    if (!me) return null;
    const rivals = st.filter(s => s.car !== sel.car && !window.isFriend(s.car, data));
    rivals.sort((a, b) => Math.abs(a.points - me.points) - Math.abs(b.points - me.points));
    return rivals[0]?.car || null;
  };
  window.enemyTag = '<span class="enemy" title="Public enemy #1: the closest rival that isn\'t one of ours">🦹 Public enemy #1</span>';
  // Snarky notes for rival pit stops (picked per car and stop, so they don't change on refresh).
  const SNARK = ["take your time", "no rush", "lovely day for it", "enjoying the view?", "scenic route", "might as well grab lunch", "bold strategy", "we'll wait"];
  window.snark = key => SNARK[[...String(key)].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % SNARK.length];
  // badge(car) -> extra HTML on a button (the Race tab shows live position / PIT).
  window.buildPicker = (el, sel, data, badge = () => "") => {
    const followed = new Map((data.standings?.cars || []).map(c => [c.car, c.class]));
    const groups = data.config?.groups?.length ? data.config.groups
      : [{ name: "Cars we follow", cars: [...followed.keys()] }];
    const button = c => `<a href="#${esc(c)}"${c === sel.car ? ' aria-current="true"' : ""}>#${esc(c)}${badge(c)}</a>`;
    const section = g => {
      const byClass = {};
      g.cars.filter(c => followed.has(c)).forEach(c => (byClass[followed.get(c)] ||= []).push(c));
      // Classes in the order their first car appears in the list (so #4, #3 come before #73).
      const cls = Object.keys(byClass);
      return cls.length ? `<div class="pick-sec"><span class="pick-title">${esc(g.name)}</span><div class="pick-row">`
        + cls.map(k => `<div><span>${NAMES[k]}</span>${byClass[k].map(button).join("")}</div>`).join("") + `</div></div>` : "";
    };
    // Every car: ours first, then everyone else by class, in championship order.
    const all = [...window.allCars(data).values()];
    const order = (a, b) => (a.pos ?? 99) - (b.pos ?? 99) || a.car.localeCompare(b.car, undefined, { numeric: true });
    const opt = c => `<option value="${esc(c.car)}"${c.car === sel.car ? " selected" : ""}>#${esc(c.car)} ${esc(c.team || "")}${c.pos ? ` · P${c.pos}` : ""}</option>`;
    const friends = all.filter(c => window.isFriend(c.car, data));
    const opts = `<optgroup label="Ours">${CLASS_ORDER.flatMap(k => friends.filter(c => c.class === k).sort(order)).map(opt).join("")}</optgroup>`
      + CLASS_ORDER.filter(k => all.some(c => c.class === k && !window.isFriend(c.car, data))).map(k =>
        `<optgroup label="${NAMES[k]}: everyone else (if you must)">${all.filter(c => c.class === k && !window.isFriend(c.car, data)).sort(order).map(opt).join("")}</optgroup>`).join("");
    const mine = !followed.has(sel.car), rival = !window.isFriend(sel.car, data);
    // Look-away banner: a rival leading our car's class (live during a session, else the championship).
    const lc = data.live?.classes?.[sel.class], fresh = data.live && !data.live.finished && Date.now() - new Date(data.live.updated) < 30 * 60e3;
    // Live leader only once the class has set times (class-by-class qualifying lists everyone else as P1).
    const hasTime = r => data.live?.is_race || (+r.laps || 0) > 0 || /[1-9]/.test(String(r.best_lap || "").replace(/^0+:/, ""));
    const liveLead = fresh && lc?.cars?.find(hasTime);
    const leader = liveLead ? liveLead.car : data.standings?.classes?.[sel.class]?.standings?.[0]?.car;
    const look = leader && !window.isFriend(leader, data)
      ? `<p class="lookaway">🙈 ${liveLead ? `A ${esc(window.makeOf(leader, data))} is leading ${NAMES[sel.class]}` : `A ${esc(window.makeOf(leader, data))} leads the ${NAMES[sel.class]} championship`}. We're choosing to look away.</p>` : "";
    el.innerHTML = groups.map(section).join("")
      + `<div class="pick-sec pick-any${mine ? " active" : ""}"><span class="pick-title">This is my car</span>`
      + `<select aria-label="Pick any car as my car"><option value="">Any car…</option>${opts}</select>`
      + (rival ? `<p class="allow">Not a Corvette, but we'll allow it.</p>` : "")
      + `</div>${look}`;
    el.querySelector("select").onchange = e => {
      const c = e.target.value;
      if (!c) return;
      location.hash = c;
    };
  };
})();
