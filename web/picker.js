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
    // Every car, grouped by class, in championship order.
    const all = [...window.allCars(data).values()];
    const opts = CLASS_ORDER.filter(k => all.some(c => c.class === k)).map(k => `<optgroup label="${NAMES[k]}">`
      + all.filter(c => c.class === k).sort((a, b) => (a.pos ?? 99) - (b.pos ?? 99) || a.car.localeCompare(b.car, undefined, { numeric: true }))
        .map(c => `<option value="${esc(c.car)}"${c.car === sel.car ? " selected" : ""}>#${esc(c.car)} ${esc(c.team || "")}${c.pos ? ` · P${c.pos}` : ""}</option>`).join("") + `</optgroup>`).join("");
    const mine = !followed.has(sel.car);
    el.innerHTML = groups.map(section).join("")
      + `<div class="pick-sec pick-any${mine ? " active" : ""}"><span class="pick-title">This is my car</span>`
      + `<select aria-label="Pick any car as my car"><option value="">Any car…</option>${opts}</select></div>`;
    el.querySelector("select").onchange = e => { if (e.target.value) location.hash = e.target.value; };
  };
})();
