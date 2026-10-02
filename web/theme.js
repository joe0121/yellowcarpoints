// Light / dark / auto (follows the device). Loaded in <head> so the saved choice applies before
// the page paints; the picker is added to the tab row once the page is ready.
(() => {
  const root = document.documentElement;
  const get = () => { try { return localStorage.getItem("theme") || "auto"; } catch (e) { return "auto"; } };
  const apply = t => { if (t === "auto") root.removeAttribute("data-theme"); else root.setAttribute("data-theme", t); };
  apply(get());

  // Liveries: picking a car repaints the accents, chart colours and the stripe at the top in the
  // colours that car runs. Chart palettes are checked for colour-blind separation in both modes;
  // the selected car's colour goes first and the others move round so nothing clashes with it.
  const LIVERIES = {
    corvette: { name: "Corvette Racing yellow", band: ["#eda100", "#111111", "#eda100"],
      light: { accent: "#eda100", ink: "#8a5d00", on: "#111", hl: "#fdf3dc", s: ["#eda100", "#2a78d6", "#1baf7a", "#eb6834"], other: "#2a78d6" },
      dark:  { accent: "#eda100", ink: "#f5c04a", on: "#111", hl: "#2a2414", s: ["#c98500", "#3987e5", "#199e70", "#d95926"], other: "#3987e5" } },
    awa: { name: "13 Autosport black and gold", band: ["#111111", "#c9a03c", "#111111"],
      light: { accent: "#c9a03c", ink: "#7a5a12", on: "#111", hl: "#f6efdf", s: ["#b8862b", "#2a78d6", "#1baf7a", "#eb6834"], other: "#2a78d6" },
      dark:  { accent: "#c9a03c", ink: "#dcb768", on: "#111", hl: "#25211a", s: ["#b08a34", "#3987e5", "#199e70", "#d95926"], other: "#3987e5" } },
    dxdt: { name: "DXDT blue and green", band: ["#1f5fd1", "#19b3a0", "#7ed321"],
      light: { accent: "#1f63d0", ink: "#1a56b8", on: "#fff", hl: "#e6effc", s: ["#2a78d6", "#eda100", "#1baf7a", "#eb6834"], other: "#eda100" },
      dark:  { accent: "#3987e5", ink: "#7fb2f5", on: "#fff", hl: "#14233a", s: ["#3987e5", "#c98500", "#199e70", "#d95926"], other: "#c98500" } },
    dragonspeed: { name: "DragonSpeed Evel Knievel white, blue and red", band: ["#1d2a6b", "#ffffff", "#d0202e", "#ffffff", "#1d2a6b"],
      light: { accent: "#2d3a9e", ink: "#2d3a9e", on: "#fff", hl: "#eceefa", s: ["#4b5bd6", "#eda100", "#1baf7a", "#eb6834"], other: "#eda100" },
      dark:  { accent: "#6f82ec", ink: "#a3b0ff", on: "#111", hl: "#1b1f38", s: ["#6f82ec", "#c98500", "#199e70", "#d95926"], other: "#c98500" } },
    prattmiller73: { name: "Pratt Miller LMP2 black and orange", band: ["#111111", "#f26b1d", "#111111"],
      light: { accent: "#f26b1d", ink: "#b4470a", on: "#111", hl: "#fdeadf", s: ["#eb6834", "#2a78d6", "#1baf7a", "#eda100"], other: "#2a78d6" },
      dark:  { accent: "#f27a33", ink: "#ff9a5c", on: "#111", hl: "#2b1d14", s: ["#d95926", "#3987e5", "#199e70", "#c98500"], other: "#3987e5" } },
  };
  const CAR_LIVERY = { 3: "corvette", 4: "corvette", 13: "awa", 36: "dxdt", 74: "dragonspeed", 81: "dragonspeed", 73: "prattmiller73" };
  const dark = () => root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
  let livery = (() => { try { return localStorage.getItem("livery"); } catch (e) { return null; } })() || "corvette";
  const paint = () => {
    const L = LIVERIES[livery] || LIVERIES.corvette, v = dark() ? L.dark : L.light, st = root.style;
    st.setProperty("--accent", v.accent); st.setProperty("--accent-ink", v.ink); st.setProperty("--on-accent", v.on);
    st.setProperty("--row-hl", v.hl); st.setProperty("--series-2", v.other);
    v.s.forEach((c, i) => st.setProperty(`--s${i + 1}`, c));
    const n = L.band.length;
    st.setProperty("--livery", `linear-gradient(90deg, ${L.band.map((c, i) => `${c} ${(i / n * 100).toFixed(1)}% ${((i + 1) / n * 100).toFixed(1)}%`).join(", ")})`);
    document.querySelector(".livery-band")?.setAttribute("title", `#${carNow || ""} livery: ${L.name}`.replace("# livery", "Livery"));
  };
  let carNow = null;
  // Called by the pages whenever the selected car changes.
  window.setLivery = car => {
    carNow = car;
    const key = CAR_LIVERY[car] || "corvette";
    if (key !== livery) { livery = key; try { localStorage.setItem("livery", key); } catch (e) {} }
    paint();
  };
  paint();
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", paint);
  const OPTIONS = [["auto", "Auto", "Match this device"], ["light", "Light", "Light mode"], ["dark", "Dark", "Dark mode"]];
  document.addEventListener("DOMContentLoaded", () => {
    const band = document.createElement("div");
    band.className = "livery-band";
    band.setAttribute("aria-hidden", "true");
    document.body.prepend(band);
    paint();
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
      apply(v); paint(); draw();
    });
    draw();
    row.appendChild(box);
  });
})();
