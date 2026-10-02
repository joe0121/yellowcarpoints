// Current track outline behind the page, in the selected car's livery colour. Outlines are drawn
// from OpenStreetMap data (© OpenStreetMap contributors, ODbL), matched to the current event.
(() => {
  const TRACKS = [
    { name: "Michelin Raceway Road Atlanta", match: /road atlanta|michelin raceway|petit le mans/i, w: 482, h: 1000,
      path: "M286.9 507.2 L288.8 499.8 L293.1 486.2 L300.1 461.8 L305.6 444.1 L308.6 437.4 L309.9 435.1 L312.3 431.5 L316.4 426.5 L318.8 423.8 L321.7 421.1 L325.2 417.8 L329.2 414.7 L336.3 410.0 L341.5 407.5 L352.0 403.1 L362.1 399.3 L367.0 397.7 L373.5 395.6 L376.0 394.3 L378.0 392.3 L379.6 389.9 L380.3 388.2 L382.6 380.2 L384.4 370.5 L385.9 363.6 L387.2 359.2 L389.1 353.8 L394.7 342.0 L399.4 333.7 L405.0 325.8 L411.9 317.5 L423.4 306.3 L435.0 295.7 L446.0 285.6 L448.1 282.9 L451.5 279.1 L455.7 274.4 L458.9 269.3 L461.9 264.1 L464.3 259.3 L467.8 252.8 L470.6 246.9 L473.5 239.5 L475.8 233.9 L479.0 224.8 L480.3 220.4 L481.2 216.2 L481.9 211.6 L482.2 207.5 L482.2 203.0 L481.8 199.2 L481.1 194.9 L479.9 190.7 L477.6 185.3 L474.1 179.8 L470.4 174.5 L465.0 167.7 L460.0 162.2 L452.8 155.3 L442.0 146.8 L435.8 142.1 L427.9 136.9 L383.1 108.5 L257.4 28.0 L223.3 7.4 L218.5 5.3 L209.3 3.0 L203.0 1.5 L196.3 0.5 L190.8 0.0 L185.6 0.1 L179.2 0.6 L174.8 1.4 L170.0 2.7 L161.6 5.6 L151.9 9.6 L138.9 15.8 L125.6 22.6 L102.5 34.2 L94.8 38.2 L87.6 42.7 L85.8 43.8 L80.7 47.1 L75.5 52.0 L71.6 55.6 L67.5 60.5 L60.0 72.3 L57.1 77.5 L53.4 83.1 L44.3 102.0 L37.3 115.7 L33.2 123.5 L31.3 127.9 L30.2 132.1 L30.1 136.4 L30.5 140.3 L31.2 143.6 L32.2 146.4 L33.7 149.0 L35.4 150.9 L45.6 159.1 L56.1 167.8 L57.3 169.0 L58.1 170.2 L58.5 172.1 L58.5 174.3 L58.2 176.4 L57.5 180.3 L45.4 223.2 L40.8 240.4 L33.8 266.9 L26.4 294.4 L20.2 316.5 L12.6 343.4 L9.3 358.4 L6.0 374.8 L3.9 387.9 L2.6 399.4 L0.7 417.1 L0.3 424.5 L0.0 433.4 L0.0 444.0 L0.2 453.2 L1.2 470.6 L3.4 490.0 L18.3 602.2 L24.2 648.7 L38.4 763.4 L40.0 776.9 L41.5 796.4 L42.5 816.2 L42.6 820.9 L42.8 827.6 L42.7 836.3 L42.3 843.7 L42.0 850.1 L41.5 857.3 L40.6 866.3 L39.8 872.3 L38.7 880.4 L35.2 899.3 L31.6 917.2 L30.0 927.4 L28.8 936.8 L25.7 962.0 L23.9 980.3 L23.6 985.5 L23.9 989.2 L24.6 991.8 L26.4 994.5 L28.2 996.3 L30.7 998.4 L34.3 999.5 L38.9 1000.0 L46.9 999.7 L57.0 999.0 L79.2 997.6 L98.1 996.1 L102.7 995.2 L106.1 994.5 L111.2 992.5 L114.8 990.3 L117.3 988.4 L121.4 984.9 L123.6 982.4 L125.8 979.3 L128.6 974.6 L129.9 971.2 L130.9 967.7 L131.7 963.8 L132.2 958.7 L131.9 951.1 L130.5 933.4 L129.4 914.2 L127.3 874.0 L126.7 855.4 L126.1 833.2 L126.1 811.7 L128.4 749.9 L129.4 736.6 L130.6 723.0 L132.3 700.4 L133.7 677.2 L134.1 656.9 L134.4 652.5 L134.9 647.2 L135.7 643.5 L136.5 640.2 L138.1 636.7 L139.8 634.0 L141.8 631.4 L144.2 629.2 L146.7 627.4 L150.6 625.3 L154.2 624.2 L162.1 622.2 L165.6 620.7 L169.6 619.1 L172.6 617.7 L176.8 615.4 L183.6 611.4 L186.7 609.1 L188.7 607.3 L191.3 604.4 L196.1 598.1 L199.6 593.0 L203.8 587.2 L207.9 582.3 L212.5 577.7 L215.8 574.4 L218.3 572.5 L221.6 570.1 L225.2 567.2 L228.1 565.4 L231.8 563.5 L236.8 561.0 L247.2 556.9 L256.4 553.1 L259.4 551.6 L262.4 549.7 L265.3 547.4 L268.3 544.7 L272.0 540.8 L276.8 534.6 L278.8 531.8 L280.9 528.1 L282.4 525.1 L283.8 521.7 L284.9 517.1 L286.9 507.2 Z" },
  ];
  const pick = name => TRACKS.find(t => t.match.test(name || ""));
  async function current() {
    const get = async n => { try { const r = await fetch(`data/${n}.json`, { cache: "no-cache" }); return r.ok ? await r.json() : null; } catch (e) { return null; } };
    const [live, st] = await Promise.all([get("live"), get("standings")]);
    // The event being raced now (live timing within the last 4 days), else the next one on the calendar.
    if (live?.event && Date.now() - new Date(live.updated) < 4 * 86400e3 && pick(live.event)) return pick(live.event);
    const next = Object.values(st?.classes || {}).flatMap(c => c.events || []).find(e => e.state === "upcoming");
    return pick(next?.name);
  }
  document.addEventListener("DOMContentLoaded", async () => {
    const t = await current();
    if (!t) return;
    // Small outline tiles, staggered like wallpaper. The tile is used as a mask over the livery
    // colour, so it follows the selected car without redrawing.
    const pad = 120, vb = `${-pad} ${-pad} ${t.w + 2 * pad} ${t.h + 2 * pad}`;
    const tile = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb}"><path d="${t.path}" fill="none" stroke="#000" stroke-width="22" stroke-linejoin="round"/></svg>`;
    const url = `url("data:image/svg+xml,${encodeURIComponent(tile)}")`;
    const bg = document.createElement("div");
    bg.className = "track-bg";
    bg.setAttribute("aria-hidden", "true");
    for (const k of ["maskImage", "webkitMaskImage"]) bg.style[k] = `${url}, ${url}`;
    document.body.prepend(bg);
    const credit = document.querySelector(".footlinks");
    if (credit) credit.insertAdjacentHTML("beforeend", `<span class="osm">${t.name} outline © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors</span>`);
  });
})();
