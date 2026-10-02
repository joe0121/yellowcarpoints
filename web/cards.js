// Every card gets a small toggle in its header to fold it away; folded cards are remembered on
// this device. Pages listen for "cardtoggle" to redraw charts at full width when a card reopens.
(() => {
  const KEY = "collapsed";
  const load = () => { try { return new Set(JSON.parse(localStorage.getItem(KEY) || "[]")); } catch (e) { return new Set(); } };
  const save = set => { try { localStorage.setItem(KEY, JSON.stringify([...set])); } catch (e) {} };
  const folded = load();
  document.querySelectorAll("section.card[id]").forEach(card => {
    let head = card.querySelector(":scope > .pace-head, :scope > .card-head");
    if (!head) {
      const h2 = card.querySelector(":scope > h2");
      if (!h2) return;
      head = document.createElement("div");
      h2.replaceWith(head);
      head.append(h2);
    }
    head.classList.add("card-head");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "fold-btn";
    const set = on => {
      card.classList.toggle("collapsed", on);
      btn.setAttribute("aria-expanded", String(!on));
      btn.title = on ? "Show this card" : "Hide this card";
      btn.textContent = on ? "Show" : "Hide";
    };
    btn.onclick = () => {
      const on = !card.classList.contains("collapsed");
      set(on);
      on ? folded.add(card.id) : folded.delete(card.id);
      save(folded);
      window.dispatchEvent(new CustomEvent("cardtoggle", { detail: { id: card.id, collapsed: on } }));
    };
    head.append(btn);
    set(folded.has(card.id));
  });
})();

// Arrange: drag cards (or use the arrows) to reorder them, within and between columns. The order is
// saved per page in this browser (and synced by "Save settings"); "Copy layout" gives a short code.
(() => {
  const groups = () => [...document.querySelectorAll("[data-layout]")];
  if (!groups().length) return;
  const page = groups()[0].dataset.layout, KEY = "layout-" + page;
  const cardsIn = c => [...c.children].filter(el => el.matches(".card[id]"));
  const read = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } };
  const current = () => Object.fromEntries(groups().map(g => [g.dataset.slot, cardsIn(g).map(c => c.id)]));
  const defaults = current();
  // One running order across the slots, for single-column (phone) layouts.
  const setOrder = () => { let i = 0; groups().forEach(g => cardsIn(g).forEach(c => { c.style.order = String(++i); })); };
  function apply(layout) {
    if (!layout) return;
    const all = new Map(groups().flatMap(g => cardsIn(g)).map(c => [c.id, c]));
    for (const g of groups()) for (const id of layout[g.dataset.slot] || []) if (all.has(id)) g.appendChild(all.get(id));
    setOrder();
  }
  const save = () => { try { localStorage.setItem(KEY, JSON.stringify(current())); } catch (e) {} setOrder(); window.dispatchEvent(new CustomEvent("cardtoggle")); };
  apply(read());

  let bar = null, dragging = null;
  const move = (card, dir) => {
    const g = card.parentElement, list = cardsIn(g), i = list.indexOf(card);
    if (dir === "up" && i > 0) g.insertBefore(card, list[i - 1]);
    if (dir === "down" && i < list.length - 1) g.insertBefore(list[i + 1], card);
    if (dir === "side") { const gs = groups(), other = gs[(gs.indexOf(g) + 1) % gs.length]; if (other !== g) other.prepend(card); }
    save(); card.scrollIntoView({ block: "nearest" });
  };
  function start() {
    document.body.classList.add("arranging");
    for (const c of groups().flatMap(cardsIn)) {
      c.draggable = true;
      const ctl = document.createElement("div");
      ctl.className = "arrange-ctl";
      ctl.innerHTML = `<span class="grip" title="Drag to move">⠿</span><button type="button" data-d="up" title="Move up">▲</button><button type="button" data-d="down" title="Move down">▼</button>`
        + (groups().length > 1 ? `<button type="button" data-d="side" title="Move to the other column">⇄</button>` : "");
      ctl.onclick = e => { const d = e.target.closest("button")?.dataset.d; if (d) move(c, d); };
      c.prepend(ctl);
      c.ondragstart = e => { dragging = c; c.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", c.id); };
      c.ondragend = () => { c.classList.remove("dragging"); dragging = null; save(); };
    }
    for (const g of groups()) g.ondragover = e => {
      if (!dragging) return;
      e.preventDefault();
      const after = cardsIn(g).filter(c => c !== dragging).find(c => e.clientY < c.getBoundingClientRect().top + c.offsetHeight / 2);
      after ? g.insertBefore(dragging, after) : g.appendChild(dragging);
    };
    bar = document.createElement("div");
    bar.className = "arrange-bar";
    bar.innerHTML = `<b>Arranging cards</b> <span class="dim">drag them, or use the arrows</span>
      <button type="button" data-a="done">Done</button><button type="button" data-a="reset">Reset to default</button><button type="button" data-a="copy">Copy layout</button><span class="copied" aria-live="polite"></span>`;
    bar.onclick = e => {
      const a = e.target.dataset.a;
      if (a === "done") stop();
      if (a === "reset") { try { localStorage.removeItem(KEY); } catch (err) {} apply(defaults); save(); try { localStorage.removeItem(KEY); } catch (err) {} }
      if (a === "copy") { const code = `${page}:${JSON.stringify(current())}`; navigator.clipboard?.writeText(code); bar.querySelector(".copied").textContent = "Copied: paste it to Claude"; }
    };
    document.body.appendChild(bar);
  }
  function stop() {
    document.body.classList.remove("arranging");
    document.querySelectorAll(".arrange-ctl").forEach(x => x.remove());
    groups().flatMap(cardsIn).forEach(c => { c.draggable = false; c.ondragstart = c.ondragend = null; });
    groups().forEach(g => { g.ondragover = null; });
    bar?.remove(); bar = null;
  }
  document.addEventListener("DOMContentLoaded", () => {
    const row = document.querySelector(".navrow");
    if (!row) return;
    const b = document.createElement("button");
    b.type = "button"; b.className = "acct-btn"; b.textContent = "Arrange";
    b.title = "Move the cards around; saved in this browser";
    b.onclick = () => document.body.classList.contains("arranging") ? stop() : start();
    row.appendChild(b);
  });
})();
