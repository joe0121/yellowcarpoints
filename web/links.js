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
  // Simple monochrome platform icons (drawn here, nothing loaded from elsewhere); they take the text colour.
  const svg = body => `<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">${body}</svg>`;
  const ICONS = {
    Website: svg(`<g fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18M5 7.5h14M5 16.5h14"/></g>`),
    "IMSA team page": svg(`<path d="M5 21V3" stroke="currentColor" stroke-width="2"/><path d="M6 4h13v9H6z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6 4h3.25v3H6zM12.5 4h3.25v3H12.5zM9.25 7h3.25v3H9.25zM15.75 7H19v3h-3.25zM6 10h3.25v3H6zM12.5 10h3.25v3H12.5z" fill="currentColor"/>`),
    X: svg(`<path d="M4.5 3.5h4.2l10.8 17h-4.2z" fill="currentColor"/><path d="M19 3.5 5 20.5" stroke="currentColor" stroke-width="1.8"/>`),
    Instagram: svg(`<rect x="3" y="3" width="18" height="18" rx="5" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="4.2" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="17.4" cy="6.6" r="1.3" fill="currentColor"/>`),
    Facebook: svg(`<circle cx="12" cy="12" r="10" fill="currentColor"/><path d="M13.4 21.9v-7.4h2.4l.4-2.9h-2.8V9.8c0-.8.3-1.4 1.4-1.4h1.5V5.8c-.3 0-1.2-.1-2.2-.1-2.2 0-3.6 1.3-3.6 3.7v2.2H8.1v2.9h2.4v7.3" fill="var(--surface)"/>`),
    YouTube: svg(`<rect x="2" y="5" width="20" height="14" rx="4.5" fill="currentColor"/><path d="M10 9v6l5.2-3z" fill="var(--surface)"/>`),
    LinkedIn: svg(`<rect x="3" y="3" width="18" height="18" rx="3" fill="currentColor"/><path d="M7 10v7M7 7.2v.1M11 17v-7M11 13.2c0-2 1.2-3.2 2.8-3.2s2.4 1 2.4 3V17" fill="none" stroke="var(--surface)" stroke-width="2" stroke-linecap="round"/>`),
  };
  const text = ([label, url]) => `<a href="${url}" target="_blank" rel="noopener">${label}</a>`;
  const icon = name => ([label, url]) => `<a class="ico" href="${url}" target="_blank" rel="noopener" title="${name}: ${label}" aria-label="${name} ${label}">${ICONS[label] || label}</a>`;
  window.renderLinks = car => {
    const el = document.getElementById("links");
    if (!el) return;
    const teams = (CAR_TEAMS[car] || []).map(k => TEAMS[k]);
    el.innerHTML = `<span class="lgrp">${IMSA.map(text).join("")}</span>`
      + (teams.length ? `<span class="lgrp socials"><span class="lbl">Team Socials</span>`
        + teams.map(t => `<span class="team"><b>${t.name}</b>${t.links.map(icon(t.name)).join("")}</span>`).join("") + `</span>` : "");
  };
})();
