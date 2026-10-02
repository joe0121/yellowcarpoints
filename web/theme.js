// Light / dark / auto (follows the device). Loaded in <head> so the saved choice applies before
// the page paints; the picker is added to the tab row once the page is ready.
(() => {
  const root = document.documentElement;
  const get = () => { try { return localStorage.getItem("theme") || "auto"; } catch (e) { return "auto"; } };
  const apply = t => { if (t === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t); };
  apply(get());
  const OPTIONS = [["auto", "Auto", "Match this device"], ["light", "Light", "Light mode"], ["dark", "Dark", "Dark mode"]];
  document.addEventListener("DOMContentLoaded", () => {
    const row = document.querySelector(".navrow");
    if (!row) return;
    const box = document.createElement("div");
    box.className = "theme";
    box.setAttribute("role", "radiogroup");
    box.setAttribute("aria-label", "Colour theme");
    const draw = () => {
      const cur = get();
      box.innerHTML = OPTIONS.map(([v, label, title]) =>
        `<button type="button" role="radio" aria-checked="${v === cur}" data-v="${v}" title="${title}">${label}</button>`).join("");
    };
    box.addEventListener("click", e => {
      const v = e.target.closest("button")?.dataset.v;
      if (!v) return;
      try { localStorage.setItem("theme", v); } catch (err) {}
      apply(v); draw();
    });
    draw();
    row.appendChild(box);
  });
})();
