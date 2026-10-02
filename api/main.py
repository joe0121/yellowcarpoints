"""Small API for yellowcarpoints.win: anonymous accounts (sync code and/or passkey), saved
settings, and a guest book that the site owner approves.

Nothing personal is stored: an account is a random id with a keyed hash of its sync code and/or
passkey public keys. Settings are an opaque JSON blob of display preferences. Client addresses are
used only in memory for rate limiting and never written to disk.

Public routes live under /api. Admin routes (/api/admin/...) need the X-Admin header, which only
the local status server (127.0.0.1:8089) adds; the public site strips it and refuses that path.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                      ResidentKeyRequirement, UserVerificationRequirement)

from words import WORDS

DB_PATH = os.environ.get("DB_PATH", "/db/site.db")
SECRET = os.environ.get("API_SECRET", "")            # keys the sync-code hash; set in .env
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
RP_ID = os.environ.get("RP_ID", "yellowcarpoints.win")
RP_NAME = "Yellow Car Points"
ORIGINS = [o.strip() for o in os.environ.get("ORIGINS", "https://yellowcarpoints.win,https://www.yellowcarpoints.win").split(",") if o.strip()]
TURNSTILE_SECRET = os.environ.get("TURNSTILE_SECRET", "")
TURNSTILE_SITEKEY = os.environ.get("TURNSTILE_SITEKEY", "")
MAX_SETTINGS = 16_000
if len(SECRET) < 32:
    raise SystemExit("API_SECRET must be set (32+ random characters) so sync codes are stored keyed")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


# --- storage ----------------------------------------------------------------------------------

def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


with db() as con:
    con.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS accounts (id INTEGER PRIMARY KEY, code_hash TEXT UNIQUE, user_handle TEXT NOT NULL,
                                         created INTEGER NOT NULL, last_seen INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, account_id INTEGER NOT NULL, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS passkeys (cred_id TEXT PRIMARY KEY, account_id INTEGER NOT NULL, public_key BLOB NOT NULL,
                                         sign_count INTEGER NOT NULL, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS settings (account_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS guestbook (id INTEGER PRIMARY KEY, name TEXT, car TEXT, message TEXT NOT NULL,
                                          created INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending');
    """)


def code_hash(code):
    norm = "-".join(re.findall(r"[a-z]+|\d+", code.lower()))
    return hmac.new(SECRET.encode(), norm.encode(), hashlib.sha256).hexdigest()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(con, account_id):
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token_hash(token), account_id, int(time.time())))
    return token


def account_for(authorization):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Not signed in")
    with db() as con:
        row = con.execute("SELECT account_id FROM sessions WHERE token_hash = ?", (token_hash(authorization[7:]),)).fetchone()
        if not row:
            raise HTTPException(401, "Session expired: sign in again")
        con.execute("UPDATE accounts SET last_seen = ? WHERE id = ?", (int(time.time()), row["account_id"]))
        return row["account_id"]


# --- rate limiting (in memory only) ------------------------------------------------------------

_hits = defaultdict(deque)


def client_ip(request: Request):
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def limit(request, bucket, n, per):
    key = (bucket, client_ip(request))
    q, now = _hits[key], time.time()
    while q and now - q[0] > per:
        q.popleft()
    if len(q) >= n:
        raise HTTPException(429, "Too many attempts: try again in a little while")
    q.append(now)


# --- accounts: sync code -------------------------------------------------------------------------

def make_code():
    return "-".join(secrets.choice(WORDS) for _ in range(4)) + "-" + f"{secrets.randbelow(10000):04d}"


@app.get("/api/config")
def config():
    return {"turnstile_sitekey": TURNSTILE_SITEKEY or None, "passkeys": True}


@app.post("/api/account")
def create_account(request: Request):
    """New anonymous account. The code is returned once; only a keyed hash is kept."""
    limit(request, "create", 5, 3600)
    code, now = make_code(), int(time.time())
    with db() as con:
        cur = con.execute("INSERT INTO accounts (code_hash, user_handle, created, last_seen) VALUES (?, ?, ?, ?)",
                          (code_hash(code), bytes_to_base64url(secrets.token_bytes(16)), now, now))
        token = new_session(con, cur.lastrowid)
    return {"code": code, "token": token}


@app.post("/api/login")
async def login(request: Request):
    limit(request, "login", 10, 300)
    body = await request.json()
    code = str(body.get("code", ""))[:100]
    with db() as con:
        row = con.execute("SELECT id FROM accounts WHERE code_hash = ?", (code_hash(code),)).fetchone()
        if not row:
            raise HTTPException(404, "That code doesn't match a saved profile")
        return {"token": new_session(con, row["id"])}


@app.post("/api/logout")
def logout(authorization: str = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        with db() as con:
            con.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(authorization[7:]),))
    return {"ok": True}


@app.delete("/api/account")
def delete_account(authorization: str = Header(None)):
    """Delete everything for this account: code, passkeys, sessions and settings."""
    aid = account_for(authorization)
    with db() as con:
        for t in ("sessions", "passkeys", "settings"):
            con.execute(f"DELETE FROM {t} WHERE account_id = ?", (aid,))
        con.execute("DELETE FROM accounts WHERE id = ?", (aid,))
    return {"ok": True}


@app.get("/api/me")
def me(authorization: str = Header(None)):
    aid = account_for(authorization)
    with db() as con:
        n = con.execute("SELECT COUNT(*) FROM passkeys WHERE account_id = ?", (aid,)).fetchone()[0]
        has_code = con.execute("SELECT code_hash IS NOT NULL FROM accounts WHERE id = ?", (aid,)).fetchone()[0]
    return {"passkeys": n, "code": bool(has_code)}


# --- settings ------------------------------------------------------------------------------------

@app.get("/api/settings")
def get_settings(authorization: str = Header(None)):
    aid = account_for(authorization)
    with db() as con:
        row = con.execute("SELECT data, updated FROM settings WHERE account_id = ?", (aid,)).fetchone()
    return {"settings": json.loads(row["data"]) if row else {}, "updated": row["updated"] if row else None}


@app.put("/api/settings")
async def put_settings(request: Request, authorization: str = Header(None)):
    aid = account_for(authorization)
    limit(request, "settings", 60, 60)
    raw = await request.body()
    if len(raw) > MAX_SETTINGS:
        raise HTTPException(413, "Settings too large")
    data = json.loads(raw or b"{}").get("settings")
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise HTTPException(400, "Settings must be an object of strings")
    with db() as con:
        con.execute("INSERT INTO settings VALUES (?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET data = excluded.data, updated = excluded.updated",
                    (aid, json.dumps(data), int(time.time())))
    return {"ok": True}


# --- passkeys (WebAuthn) -------------------------------------------------------------------------

_challenges = {}   # id -> (challenge bytes, account id or None, expiry)


def keep_challenge(challenge, account_id=None):
    now = time.time()
    for k in [k for k, v in _challenges.items() if v[2] < now]:
        del _challenges[k]
    cid = secrets.token_urlsafe(16)
    _challenges[cid] = (challenge, account_id, now + 300)
    return cid


def take_challenge(cid):
    c = _challenges.pop(cid or "", None)
    if not c or c[2] < time.time():
        raise HTTPException(400, "Passkey request expired: try again")
    return c


@app.post("/api/passkey/register/options")
def passkey_register_options(request: Request, authorization: str = Header(None)):
    """Add a passkey to the signed-in account (creating one first if needed is done by the page)."""
    aid = account_for(authorization)
    limit(request, "passkey", 20, 300)
    with db() as con:
        handle = con.execute("SELECT user_handle FROM accounts WHERE id = ?", (aid,)).fetchone()[0]
        existing = [r[0] for r in con.execute("SELECT cred_id FROM passkeys WHERE account_id = ?", (aid,))]
    opts = generate_registration_options(
        rp_id=RP_ID, rp_name=RP_NAME, user_id=base64url_to_bytes(handle), user_name="Yellow Car Points fan",
        user_display_name="Yellow Car Points fan",
        authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
                                                               user_verification=UserVerificationRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in existing])
    return {"challenge_id": keep_challenge(opts.challenge, aid), "options": json.loads(options_to_json(opts))}


@app.post("/api/passkey/register/verify")
async def passkey_register_verify(request: Request, authorization: str = Header(None)):
    aid = account_for(authorization)
    body = await request.json()
    challenge, owner, _ = take_challenge(body.get("challenge_id"))
    if owner != aid:
        raise HTTPException(400, "Passkey request doesn't match this account")
    try:
        v = verify_registration_response(credential=body["credential"], expected_challenge=challenge,
                                         expected_origin=ORIGINS, expected_rp_id=RP_ID, require_user_verification=False)
    except Exception as e:
        raise HTTPException(400, f"Passkey not accepted: {e}")
    with db() as con:
        con.execute("INSERT OR REPLACE INTO passkeys VALUES (?, ?, ?, ?, ?)",
                    (bytes_to_base64url(v.credential_id), aid, v.credential_public_key, v.sign_count, int(time.time())))
    return {"ok": True}


@app.post("/api/passkey/login/options")
def passkey_login_options(request: Request):
    limit(request, "passkey", 20, 300)
    opts = generate_authentication_options(rp_id=RP_ID, user_verification=UserVerificationRequirement.PREFERRED)
    return {"challenge_id": keep_challenge(opts.challenge), "options": json.loads(options_to_json(opts))}


@app.post("/api/passkey/login/verify")
async def passkey_login_verify(request: Request):
    limit(request, "login", 10, 300)
    body = await request.json()
    challenge, _, _ = take_challenge(body.get("challenge_id"))
    cred = body.get("credential") or {}
    with db() as con:
        row = con.execute("SELECT * FROM passkeys WHERE cred_id = ?", (cred.get("rawId") or cred.get("id"),)).fetchone()
        if not row:
            raise HTTPException(404, "That passkey isn't registered here")
        try:
            v = verify_authentication_response(credential=cred, expected_challenge=challenge, expected_rp_id=RP_ID,
                                               expected_origin=ORIGINS, credential_public_key=row["public_key"],
                                               credential_current_sign_count=row["sign_count"], require_user_verification=False)
        except Exception as e:
            raise HTTPException(400, f"Passkey not accepted: {e}")
        con.execute("UPDATE passkeys SET sign_count = ? WHERE cred_id = ?", (v.new_sign_count, row["cred_id"]))
        return {"token": new_session(con, row["account_id"])}


# --- guest book --------------------------------------------------------------------------------

def clean(s, n):
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(s or "")).strip()
    return s[:n]


def turnstile_ok(token, ip):
    if not TURNSTILE_SECRET:
        return True
    data = urllib.parse.urlencode({"secret": TURNSTILE_SECRET, "response": token or "", "remoteip": ip}).encode()
    try:
        with urllib.request.urlopen("https://challenges.cloudflare.com/turnstile/v0/siteverify", data, timeout=10) as r:
            return bool(json.load(r).get("success"))
    except Exception:
        return False


@app.get("/api/guestbook")
def guestbook():
    with db() as con:
        rows = con.execute("SELECT id, name, car, message, created FROM guestbook WHERE status = 'approved' ORDER BY created DESC LIMIT 200").fetchall()
    return {"entries": [dict(r) for r in rows]}


@app.post("/api/guestbook")
async def sign_guestbook(request: Request):
    body = await request.json()
    if body.get("website"):            # honeypot field real people never see
        return {"ok": True, "status": "pending"}
    limit(request, "guestbook", 3, 3600)
    message = clean(body.get("message"), 500)
    if len(message) < 2:
        raise HTTPException(400, "Write a message first")
    if not turnstile_ok(body.get("turnstile"), client_ip(request)):
        raise HTTPException(400, "The spam check didn't pass: reload the page and try again")
    with db() as con:
        con.execute("INSERT INTO guestbook (name, car, message, created) VALUES (?, ?, ?, ?)",
                    (clean(body.get("name"), 40) or None, clean(body.get("car"), 8) or None, message, int(time.time())))
    return {"ok": True, "status": "pending"}


# --- admin (local status page only) ------------------------------------------------------------

def admin(x_admin):
    if not ADMIN_TOKEN or not hmac.compare_digest(x_admin or "", ADMIN_TOKEN):
        raise HTTPException(404)


@app.get("/api/admin/guestbook")
def admin_list(x_admin: str = Header(None)):
    admin(x_admin)
    with db() as con:
        rows = con.execute("SELECT * FROM guestbook ORDER BY status = 'approved', created DESC LIMIT 300").fetchall()
        stats = {"accounts": con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
                 "passkeys": con.execute("SELECT COUNT(*) FROM passkeys").fetchone()[0],
                 "with_settings": con.execute("SELECT COUNT(*) FROM settings").fetchone()[0]}
    return {"entries": [dict(r) for r in rows], "stats": stats}


@app.post("/api/admin/guestbook/{entry_id}/{action}")
def admin_act(entry_id: int, action: str, x_admin: str = Header(None)):
    admin(x_admin)
    with db() as con:
        if action == "approve":
            con.execute("UPDATE guestbook SET status = 'approved' WHERE id = ?", (entry_id,))
        elif action == "delete":
            con.execute("DELETE FROM guestbook WHERE id = ?", (entry_id,))
        else:
            raise HTTPException(400)
    return {"ok": True}


@app.exception_handler(json.JSONDecodeError)
def bad_json(request, exc):
    return JSONResponse({"detail": "Bad request"}, status_code=400)
