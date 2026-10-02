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
