// Links strip under the car picker: IMSA's own site, timing and YouTube, plus the selected car's
// team accounts. Every link was checked against the team's own website or link page.
(() => {
  const IMSA = [["IMSA", "https://www.imsa.com/"], ["Live timing", "https://www.imsa.com/scoring/"], ["IMSA on YouTube", "https://www.youtube.com/@IMSAOfficial"]];
  const TEAMS = {
    corvette: { name: "Corvette Racing", links: [["Website", "https://corvetteracing.com/"], ["X", "https://x.com/CorvetteRacing"],
      ["Instagram", "https://www.instagram.com/teamchevy"], ["Facebook", "https://www.facebook.com/TeamChevy"], ["YouTube", "https://www.youtube.com/user/Chevrolet"]] },
    prattmiller: { name: "Pratt Miller Motorsports", links: [["Website", "https://www.prattmiller.com/"], ["X", "https://x.com/PrattMillerMS"],
      ["Instagram", "https://www.instagram.com/prattmillermotorsports/"], ["Facebook", "https://www.facebook.com/PrattMillerMotorsports"], ["YouTube", "https://www.youtube.com/@PrattMillerMotorsports"]] },
    dxdt: { name: "DXDT Racing", links: [["Website", "https://dxdtracing.com/"], ["X", "https://x.com/DXDTRacing"],
      ["Instagram", "https://www.instagram.com/dxdt_racing/"], ["Facebook", "https://www.facebook.com/dxdtracing/"]] },
    dragonspeed: { name: "DragonSpeed", links: [["IMSA team page", "https://www.imsa.com/racing-teams/dragonspeed-no-81/"], ["X", "https://x.com/DragonSpeedLLC"],
      ["Instagram", "https://www.instagram.com/dragonspeed_official/"], ["LinkedIn", "https://www.linkedin.com/company/dragonspeed-llc"]] },
    autosport13: { name: "13 Autosport", links: [["IMSA team page", "https://www.imsa.com/racing-teams/awa-no-13/"]] },
    awa: { name: "AWA (runs the car)", links: [["Website", "https://awa.team/"], ["Instagram", "https://www.instagram.com/awaracingteam/"]] },
  };
  const CAR_TEAMS = { 3: ["corvette", "prattmiller"], 4: ["corvette", "prattmiller"], 73: ["prattmiller"],
    74: ["dragonspeed"], 81: ["dragonspeed"], 13: ["autosport13", "awa"], 36: ["dxdt"] };
  const a = ([label, url]) => `<a href="${url}" target="_blank" rel="noopener">${label}</a>`;
  window.renderLinks = car => {
    const el = document.getElementById("links");
    if (!el) return;
    const teams = (CAR_TEAMS[car] || []).map(k => TEAMS[k]);
    el.innerHTML = `<span class="lgrp">${IMSA.map(a).join("")}</span>`
      + teams.map(t => `<span class="lgrp"><b>${car ? `#${car} ` : ""}${t.name}</b>${t.links.map(a).join("")}</span>`).join("");
  };
})();
