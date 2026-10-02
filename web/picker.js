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
  // A stadium crowd booing, made with the browser's audio (no sound file): ~18 voices at different
  // pitches, each starting a moment apart with its own wobble, shaped into an "oo" vowel (formants
  // near 300 and 870 Hz), over a bed of crowd noise. Only on a deliberate pick; mutable.
  const muted = () => { try { return localStorage.getItem("booOff") === "1"; } catch (e) { return false; } };
  window.boo = () => {
    if (muted()) return;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)(), t = ctx.currentTime, end = t + 2.6;
      const master = ctx.createGain();
      master.gain.setValueAtTime(0.0001, t);
      master.gain.exponentialRampToValueAtTime(0.35, t + 0.45);     // the crowd joins in
      master.gain.setValueAtTime(0.35, t + 1.5);
      master.gain.exponentialRampToValueAtTime(0.0001, end);       // and trails off
      master.connect(ctx.destination);
      // "oo" vowel: two formant band-passes mixed, then a gentle low-pass.
      const lp = ctx.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 1300; lp.connect(master);
      const vowel = ctx.createGain();
      for (const [f, q, g] of [[300, 4, 1], [870, 6, 0.45]]) {
        const bp = ctx.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = f; bp.Q.value = q;
        const bg = ctx.createGain(); bg.gain.value = g; vowel.connect(bp); bp.connect(bg); bg.connect(lp);
      }
      const rnd = (a, b) => a + Math.random() * (b - a);
      for (let i = 0; i < 18; i++) {
        const start = t + rnd(0, 0.35), stop = end - rnd(0, 0.5);
        const base = i % 3 === 2 ? rnd(200, 290) : rnd(95, 170);     // mostly low voices, some higher
        const o = ctx.createOscillator(); o.type = "sawtooth";
        o.frequency.setValueAtTime(base * 1.04, start);
        o.frequency.linearRampToValueAtTime(base * 0.86, stop);      // the slide down of a boo
        const vib = ctx.createOscillator(), vg = ctx.createGain();
        vib.frequency.value = rnd(4, 6.5); vg.gain.value = base * rnd(0.01, 0.03); vib.connect(vg); vg.connect(o.frequency);
        const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, start);
        g.gain.exponentialRampToValueAtTime(rnd(0.03, 0.06), start + rnd(0.15, 0.4));
        g.gain.setValueAtTime(g.gain.value || 0.04, stop - 0.4); g.gain.exponentialRampToValueAtTime(0.0001, stop);
        o.connect(g); g.connect(vowel);
        o.start(start); vib.start(start); o.stop(stop + 0.05); vib.stop(stop + 0.05);
      }
      // Crowd murmur: filtered noise under the voices.
      const n = ctx.createBuffer(1, ctx.sampleRate * 2.7, ctx.sampleRate), d = n.getChannelData(0);
      for (let i = 0, last = 0; i < d.length; i++) { last = 0.97 * last + 0.03 * (Math.random() * 2 - 1); d[i] = last * 6; }
      const ns = ctx.createBufferSource(); ns.buffer = n;
      const nf = ctx.createBiquadFilter(); nf.type = "bandpass"; nf.frequency.value = 450; nf.Q.value = 0.8;
      const ng = ctx.createGain(); ng.gain.value = 0.25; ns.connect(nf); nf.connect(ng); ng.connect(lp); ns.start(t);
      setTimeout(() => ctx.close(), 3200);
    } catch (e) {}
  };

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
    const leader = fresh && lc?.cars?.[0] ? lc.cars[0].car : data.standings?.classes?.[sel.class]?.standings?.[0]?.car;
    const look = leader && !window.isFriend(leader, data)
      ? `<p class="lookaway">🙈 ${fresh && lc ? `A ${esc(window.makeOf(leader, data))} is leading ${NAMES[sel.class]}` : `A ${esc(window.makeOf(leader, data))} leads the ${NAMES[sel.class]} championship`}. We're choosing to look away.</p>` : "";
    el.innerHTML = groups.map(section).join("")
      + `<div class="pick-sec pick-any${mine ? " active" : ""}"><span class="pick-title">This is my car</span>`
      + `<select aria-label="Pick any car as my car"><option value="">Any car…</option>${opts}</select>`
      + (rival ? `<p class="allow">Not a Corvette, but we'll allow it. <button type="button" class="linkbtn" data-boo>${muted() ? "Unmute boos" : "Mute boos"}</button></p>` : "")
      + `</div>${look}`;
    el.querySelector("select").onchange = e => {
      const c = e.target.value;
      if (!c) return;
      if (!window.isFriend(c, data)) window.boo();
      location.hash = c;
    };
    el.querySelector("[data-boo]")?.addEventListener("click", e => {
      try { localStorage.setItem("booOff", muted() ? "" : "1"); } catch (err) {}
      e.target.textContent = muted() ? "Unmute boos" : "Mute boos";
    });
  };
})();
