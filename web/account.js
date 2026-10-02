// Anonymous profile: save this browser's display settings and bring them to another device with a
// sync code or a passkey. No name, email or password. Adds a "Save settings" button to the tab row.
(() => {
  const SYNC_KEYS = ["car", "theme", "livery", "charts", "collapsed", "watch", "fullTiming", "deep", "layout-race", "layout-champ"];
  const ls = {
    get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} },
  };
  const token = () => ls.get("ycp_token");
  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json", ...(token() ? { Authorization: `Bearer ${token()}` } : {}) };
    const r = await fetch(`/api/${path}`, { ...opts, headers, cache: "no-store" });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `Request failed (${r.status})`);
    return body;
  }
  const snapshot = () => Object.fromEntries(SYNC_KEYS.map(k => [k, ls.get(k)]).filter(([, v]) => v != null));
  const apply = s => { SYNC_KEYS.forEach(k => ls.set(k, s[k] ?? null)); };

  // --- sync: pull once per page load, push local changes every 10 s ---
  let lastPushed = null, pulled = !token();   // never push before the saved copy has been read
  async function push() {
    if (!token() || !pulled) return;
    const s = JSON.stringify(snapshot());
    if (s === lastPushed) return;
    try { await api("settings", { method: "PUT", body: JSON.stringify({ settings: JSON.parse(s) }) }); lastPushed = s; ls.set("ycp_synced", String(Date.now() / 1000 | 0)); }
    catch (e) { if (/sign in/i.test(e.message)) ls.set("ycp_token", null); }
  }
  async function pull(reloadIfChanged) {
    const { settings, updated } = await api("settings");
    const local = JSON.stringify(snapshot());
    if (updated && updated > +(ls.get("ycp_synced") || 0) && JSON.stringify(settings) !== local && Object.keys(settings).length) {
      apply(settings);
      ls.set("ycp_synced", String(updated));
      if (reloadIfChanged) { location.reload(); return true; }
    }
    lastPushed = JSON.stringify(snapshot());
    pulled = true;
    return false;
  }
  if (token()) pull(true).catch(e => { if (/sign in/i.test(e.message)) ls.set("ycp_token", null); });
  setInterval(push, 10e3);
  addEventListener("visibilitychange", () => document.visibilityState === "hidden" && push());

  // --- passkeys: convert between the server's JSON options and the browser API ---
  const b64u = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  const unb64u = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0)).buffer;
  const toCreate = o => PublicKeyCredential.parseCreationOptionsFromJSON ? PublicKeyCredential.parseCreationOptionsFromJSON(o)
    : { ...o, challenge: unb64u(o.challenge), user: { ...o.user, id: unb64u(o.user.id) }, excludeCredentials: (o.excludeCredentials || []).map(c => ({ ...c, id: unb64u(c.id) })) };
  const toGet = o => PublicKeyCredential.parseRequestOptionsFromJSON ? PublicKeyCredential.parseRequestOptionsFromJSON(o)
    : { ...o, challenge: unb64u(o.challenge), allowCredentials: (o.allowCredentials || []).map(c => ({ ...c, id: unb64u(c.id) })) };
  const credJSON = c => {
    if (c.toJSON) return c.toJSON();
    const r = c.response, out = { id: c.id, rawId: b64u(c.rawId), type: c.type, response: { clientDataJSON: b64u(r.clientDataJSON) } };
    if (r.attestationObject) Object.assign(out.response, { attestationObject: b64u(r.attestationObject), transports: r.getTransports?.() || [] });
    if (r.authenticatorData) Object.assign(out.response, { authenticatorData: b64u(r.authenticatorData), signature: b64u(r.signature), userHandle: r.userHandle ? b64u(r.userHandle) : null });
    return out;
  };
  const passkeysOK = () => !!window.PublicKeyCredential;
  async function addPasskey() {
    const { challenge_id, options } = await api("passkey/register/options", { method: "POST" });
    const cred = await navigator.credentials.create({ publicKey: toCreate(options) });
    await api("passkey/register/verify", { method: "POST", body: JSON.stringify({ challenge_id, credential: credJSON(cred) }) });
  }
  async function passkeyLogin() {
    const { challenge_id, options } = await api("passkey/login/options", { method: "POST" });
    const cred = await navigator.credentials.get({ publicKey: toGet(options) });
    const { token: t } = await api("passkey/login/verify", { method: "POST", body: JSON.stringify({ challenge_id, credential: credJSON(cred) }) });
    return t;
  }
  async function signedIn(t, code) {
    ls.set("ycp_token", t);
    if (code) ls.set("ycp_code", code);
    ls.set("ycp_synced", "0");
    if (!(await pull(true))) location.reload();
  }

  // --- UI ---
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  document.addEventListener("DOMContentLoaded", () => {
    const row = document.querySelector(".navrow");
    if (!row) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "acct-btn";
    const label = () => { btn.textContent = token() ? "Settings saved ✓" : "Save settings"; btn.title = token() ? "Your settings sync to your anonymous profile" : "Save your settings anonymously"; };
    label();
    row.appendChild(btn);
    const dlg = document.createElement("dialog");
    dlg.className = "acct";
    document.body.appendChild(dlg);
    const msg = (t, bad) => { const m = dlg.querySelector(".acct-msg"); if (m) { m.textContent = t; m.classList.toggle("bad", !!bad); } };
    const run = fn => async () => { try { msg("Working…"); await fn(); } catch (e) { msg(e.name === "NotAllowedError" ? "Passkey cancelled." : e.message, true); } };

    function draw() {
      const code = ls.get("ycp_code");
      dlg.innerHTML = token() ? `
        <h2>Your anonymous profile</h2>
        <p>Your chosen car, theme, charts and hidden cards sync automatically on every device signed in to this profile. No name, email or password is stored.</p>
        ${code ? `<p><b>Sync code</b> (type it on another device): <code class="acct-code">${esc(code)}</code> <button type="button" class="chip" data-act="copy">Copy</button></p>` : `<p class="dim">Signed in with a passkey on this device.</p>`}
        <div class="acct-row">${passkeysOK() ? `<button type="button" class="acct-main" data-act="addpk">Add a passkey on this device</button>` : ""}
          <button type="button" class="chip" data-act="logout">Sign out here</button>
          <button type="button" class="chip danger" data-act="delete">Delete my profile</button></div>
        <p class="acct-msg" aria-live="polite"></p>
        <p class="note">A passkey lets you sign in with your phone's or computer's lock (fingerprint, face or PIN) instead of typing the code.</p>
        <form method="dialog"><button class="chip">Close</button></form>` : `
        <h2>Save your settings</h2>
        <p>Keep your chosen car, theme, charts and hidden cards, and bring them to your other devices. Completely anonymous: no name, email or password.</p>
        <div class="acct-row"><button type="button" class="acct-main" data-act="create">Create a sync code</button>
          ${passkeysOK() ? `<button type="button" class="chip" data-act="pklogin">Sign in with a passkey</button>` : ""}</div>
        <form class="acct-row" data-act="enter"><input name="code" placeholder="Have a code? e.g. wild-corn-zero-exit-9817" autocomplete="off" spellcheck="false" aria-label="Sync code">
          <button class="chip">Use code</button></form>
        <p class="acct-msg" aria-live="polite"></p>
        <p class="note">Your settings are stored on this site's server against a random code. Lose the code (and any passkey) and the saved copy can't be recovered; this browser keeps its own settings either way.</p>
        <form method="dialog"><button class="chip">Close</button></form>`;
      const on = (act, fn) => dlg.querySelector(`[data-act="${act}"]`)?.addEventListener(act === "enter" ? "submit" : "click", fn);
      on("create", run(async () => {
        const { code: c, token: t } = await api("account", { method: "POST" });
        ls.set("ycp_token", t); ls.set("ycp_code", c); lastPushed = null; pulled = true; await push(); label(); draw();
        msg("Saved. Write the code down or add a passkey, so you can sign in on other devices.");
      }));
      on("enter", e => { e.preventDefault(); run(async () => {
        const c = new FormData(e.target).get("code").trim();
        const { token: t } = await api("login", { method: "POST", body: JSON.stringify({ code: c }) });
        await signedIn(t, c.toLowerCase().replace(/\s+/g, "-"));
      })(); });
      on("pklogin", run(async () => { await signedIn(await passkeyLogin(), null); }));
      on("addpk", run(async () => { await addPasskey(); msg("Passkey added. You can now sign in with it on this device (and on others your passkey syncs to)."); }));
      on("copy", () => { navigator.clipboard?.writeText(ls.get("ycp_code") || ""); msg("Copied."); });
      on("logout", run(async () => { await api("logout", { method: "POST" }).catch(() => {}); ["ycp_token", "ycp_code", "ycp_synced"].forEach(k => ls.set(k, null)); label(); draw(); msg("Signed out on this device. Your settings here stay as they are."); }));
      let armed = false;
      on("delete", run(async () => {
        if (!armed) { armed = true; msg("Press Delete my profile again to permanently delete the saved copy, code and passkeys."); return; }
        await api("account", { method: "DELETE" });
        ["ycp_token", "ycp_code", "ycp_synced"].forEach(k => ls.set(k, null)); label(); draw(); msg("Profile deleted.");
      }));
    }
    btn.addEventListener("click", () => { draw(); dlg.showModal(); });
  });
})();
