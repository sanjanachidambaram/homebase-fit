"""Sign in with Google or Microsoft (OpenID Connect, authorization code flow with PKCE, state and nonce).

Routes:
  GET /api/auth/providers             {"google": bool, "microsoft": bool}: which buttons the frontend should show
  GET /api/auth/{provider}/start      redirects to Google / Microsoft (rate limited per IP)
  GET /api/auth/{provider}/callback   where they send the person back; signs them in and redirects to the app at
                                      PUBLIC_BASE_URL/auth/callback#token=...&user_id=...&username=...&new=0|1
                                      (or #error=... ). The token goes in the URL fragment, which browsers never send
                                      to a server, and the app moves it into the same session storage a password
                                      sign-in uses. It's the same token (app/security.py make_token).

How the flow is protected:
  * PKCE (S256): the code can only be exchanged by whoever started the sign-in.
  * state: the callback must carry the random value this browser got at /start (stops cross-site sign-in forgery).
  * nonce: the ID token must carry the value from /start (stops a replayed token).
  The three values ride in a short-lived (10 min), HMAC-signed, HttpOnly, SameSite=Lax cookie scoped to /api/auth,
  so the server keeps no state. The ID token comes straight from the provider's token endpoint over TLS, so its
  claims (issuer, audience, expiry, nonce) are checked without fetching signing keys (OpenID Connect Core 3.1.3.7).

Who signs in (find_or_create_user):
  1. This provider account signed in before (oauth_identities, provider + "sub"): that user.
  2. Else, if the provider says the email is VERIFIED and an account already has that email: link it to that account.
     Google: the email_verified claim. Microsoft: personal Microsoft accounts only (their tenant id); work / school
     accounts can carry an email their organization never verified, so they never link by email.
  3. Else: a new account (username made from the email or name, first name from the provider; no password).
  users.email is only ever set from a verified email, so nobody can pre-claim someone else's address. Never linked by
  username, even one that looks like an email. The email and name stay in the database; like the username they never
  reach an agent (app/agents/context.py).
Settings needed (environment variables, declared in render.yaml): GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
MICROSOFT_CLIENT_ID, MICROSOFT_CLIENT_SECRET, PUBLIC_BASE_URL. A provider without its id and secret is simply off.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import app_secret_key, get_secret
from app.db import Connection, IntegrityError, connect
from app.security import OAUTH_LIMIT, limiter, make_token

router = APIRouter(prefix="/api/auth")

COOKIE = "bf_oauth"
COOKIE_MAX_AGE = 600
MICROSOFT_CONSUMER_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"   # personal Microsoft accounts (outlook.com, ...)
CLOCK_SKEW = 120

PROVIDERS = {
    "google": {
        "label": "Google",
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "client_id": "GOOGLE_CLIENT_ID", "client_secret": "GOOGLE_CLIENT_SECRET",
        "scope": "openid email profile",
    },
    "microsoft": {
        "label": "Microsoft",
        # "common": personal Microsoft accounts and work / school accounts.
        "authorize": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "client_id": "MICROSOFT_CLIENT_ID", "client_secret": "MICROSOFT_CLIENT_SECRET",
        "scope": "openid email profile",
    },
}


class OAuthError(Exception):
    """A sign-in that can't complete. The message is safe to show the person."""


# ---------------------------------------------------------------- settings

def credentials(provider: str) -> tuple[str, str] | None:
    p = PROVIDERS[provider]
    cid, secret = get_secret(p["client_id"]), get_secret(p["client_secret"])
    return (cid, secret) if cid and secret else None


def public_base_url(request: Request) -> str:
    """PUBLIC_BASE_URL (https://bee-fit-app.onrender.com in production); in development, the address the request came in on."""
    return (get_secret("PUBLIC_BASE_URL") or str(request.base_url)).rstrip("/")


def redirect_uri(request: Request, provider: str) -> str:
    """Register exactly this in the Google / Microsoft app settings: <PUBLIC_BASE_URL>/api/auth/<provider>/callback."""
    return f"{public_base_url(request)}/api/auth/{provider}/callback"


# ---------------------------------------------------------------- the signed state cookie

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str) -> str:
    return hmac.new(app_secret_key().encode(), f"oauth-state.{payload}".encode(), hashlib.sha256).hexdigest()


def pack_state(data: dict) -> str:
    payload = _b64(json.dumps(data, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def unpack_state(cookie: str | None) -> dict:
    if not cookie or "." not in cookie:
        raise OAuthError("Your sign-in took too long or was started in another browser. Please try again.")
    payload, sig = cookie.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        raise OAuthError("Your sign-in couldn't be verified. Please try again.")
    data = json.loads(_unb64(payload))
    if time.time() - data.get("t", 0) > COOKIE_MAX_AGE:
        raise OAuthError("Your sign-in took too long. Please try again.")
    return data


def pkce_pair() -> tuple[str, str]:
    verifier = _b64(secrets.token_bytes(48))
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


# ---------------------------------------------------------------- the ID token

def decode_id_token(id_token: str) -> dict:
    try:
        return json.loads(_unb64(id_token.split(".")[1]))
    except (IndexError, ValueError) as e:
        raise OAuthError("The sign-in provider sent something unexpected. Please try again.") from e


def check_claims(provider: str, claims: dict, client_id: str, nonce: str, now: float | None = None) -> None:
    now = now or time.time()
    iss = claims.get("iss", "")
    ok_issuer = (iss in ("https://accounts.google.com", "accounts.google.com") if provider == "google" else
                 bool(re.fullmatch(r"https://login\.microsoftonline\.com/[0-9a-f-]{36}/v2\.0", iss))
                 and iss == f"https://login.microsoftonline.com/{claims.get('tid')}/v2.0")
    aud = claims.get("aud")
    ok_audience = aud == client_id or (isinstance(aud, list) and client_id in aud)
    if not (ok_issuer and ok_audience and claims.get("sub")):
        raise OAuthError("The sign-in provider's answer didn't check out. Please try again.")
    if float(claims.get("exp", 0)) < now - CLOCK_SKEW:
        raise OAuthError("Your sign-in expired. Please try again.")
    if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OAuthError("Your sign-in couldn't be verified. Please try again.")


def verified_email(provider: str, claims: dict) -> str | None:
    """The email, only if the provider vouches for it (see the module docstring)."""
    email = (claims.get("email") or "").strip().lower() or None
    if not email or "@" not in email:
        return None
    if provider == "google":
        return email if claims.get("email_verified") in (True, "true") else None
    if provider == "microsoft":
        edov = claims.get("xms_edov") in (True, "true", "1", 1)   # optional claim: domain owner verified the email
        return email if claims.get("tid") == MICROSOFT_CONSUMER_TENANT or edov else None
    return None


def exchange_code(provider: str, code: str, verifier: str, redirect: str) -> dict:
    """Swap the authorization code (plus the PKCE verifier) for tokens at the provider. Returns the ID token's claims."""
    cid, secret = credentials(provider)
    try:
        r = httpx.post(PROVIDERS[provider]["token"], timeout=15, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
            "client_id": cid, "client_secret": secret, "code_verifier": verifier})
    except httpx.HTTPError as e:
        raise OAuthError(f"Couldn't reach {PROVIDERS[provider]['label']}. Please try again.") from e
    if r.status_code != 200 or "id_token" not in r.json():
        raise OAuthError(f"{PROVIDERS[provider]['label']} didn't accept the sign-in. Please try again.")
    return decode_id_token(r.json()["id_token"])


# ---------------------------------------------------------------- find or create the account

USERNAME_OK = re.compile(r"[^A-Za-z0-9._-]+")


def _base_username(claims: dict) -> str:
    email = claims.get("email") or claims.get("preferred_username") or ""
    raw = email.split("@")[0] if "@" in email else (claims.get("given_name") or claims.get("name") or "")
    base = USERNAME_OK.sub("", raw.replace(" ", "."))[:24].strip("._-")
    return base if len(base) >= 3 else f"beefit.{base}".strip("._-")[:24] or "beefit"


def _unique_username(conn: Connection, base: str) -> str:
    candidate, n = base, 1
    while conn.execute("SELECT 1 FROM users WHERE username = ?", (candidate,)).fetchone():
        n += 1
        candidate = f"{base[:30 - len(str(n)) - 1]}.{n}"
    return candidate


def _first_name(claims: dict) -> str | None:
    name = claims.get("given_name") or (claims.get("name") or "").split(" ")[0]
    name = " ".join(str(name).split())[:50]
    return name or None


def find_or_create_user(conn: Connection, provider: str, claims: dict) -> tuple[int, str, bool]:
    """(user_id, username, created). The rules are in the module docstring. Runs in one transaction."""
    subject = str(claims["sub"])
    email = verified_email(provider, claims)
    shown_email = (claims.get("email") or "").strip().lower() or None
    with conn:
        hit = conn.execute("SELECT u.id, u.username FROM oauth_identities i JOIN users u ON u.id = i.user_id "
                           "WHERE i.provider = ? AND i.subject = ?", (provider, subject)).fetchone()
        if hit:
            conn.execute("UPDATE oauth_identities SET email = ?, email_verified = ?, last_login_at = "
                         "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') "
                         "WHERE provider = ? AND subject = ?", (shown_email, bool(email), provider, subject))
            return hit["id"], str(hit["username"]), False
        user = conn.execute("SELECT id, username FROM users WHERE email = ?", (email,)).fetchone() if email else None
        created = user is None
        if created:
            username = _unique_username(conn, _base_username(claims))
            uid = conn.execute("INSERT INTO users (username, first_name, password_hash, email) VALUES (?, ?, NULL, ?)",
                               (username, _first_name(claims), email)).lastrowid
        else:
            uid, username = user["id"], str(user["username"])
        conn.execute("INSERT INTO oauth_identities (user_id, provider, subject, email, email_verified) "
                     "VALUES (?, ?, ?, ?, ?)", (uid, provider, subject, shown_email, bool(email)))
    return uid, username, created


# ---------------------------------------------------------------- routes

def _back_to_app(request: Request, **fragment) -> RedirectResponse:
    response = RedirectResponse(f"{public_base_url(request)}/auth/callback#{urlencode(fragment)}", status_code=302)
    response.delete_cookie(COOKIE, path="/api/auth")
    return response


def _provider(provider: str) -> str:
    if provider not in PROVIDERS:
        raise HTTPException(404, "Unknown sign-in provider.")
    return provider


@router.get("/providers")
def providers() -> dict[str, bool]:
    return {name: credentials(name) is not None for name in PROVIDERS}


@router.get("/{provider}/start")
@limiter.limit(OAUTH_LIMIT)
def start(provider: str, request: Request) -> RedirectResponse:
    provider = _provider(provider)
    creds = credentials(provider)
    if creds is None:
        raise HTTPException(404, f"{PROVIDERS[provider]['label']} sign-in isn't set up on this server.")
    verifier, challenge = pkce_pair()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    query = {
        "client_id": creds[0], "response_type": "code", "redirect_uri": redirect_uri(request, provider),
        "scope": PROVIDERS[provider]["scope"], "state": state, "nonce": nonce,
        "code_challenge": challenge, "code_challenge_method": "S256", "prompt": "select_account",
    }
    response = RedirectResponse(f"{PROVIDERS[provider]['authorize']}?{urlencode(query)}", status_code=302)
    response.set_cookie(COOKIE, pack_state({"p": provider, "s": state, "n": nonce, "v": verifier, "t": int(time.time())}),
                        max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax", path="/api/auth",
                        secure=public_base_url(request).startswith("https://"))
    return response


@router.get("/{provider}/callback")
@limiter.limit(OAUTH_LIMIT)
def callback(provider: str, request: Request, code: str | None = None, state: str | None = None,
             error: str | None = None) -> RedirectResponse:
    provider = _provider(provider)
    try:
        if error:   # the person cancelled, or the provider refused
            raise OAuthError(f"{PROVIDERS[provider]['label']} sign-in was cancelled.")
        if credentials(provider) is None:
            raise OAuthError(f"{PROVIDERS[provider]['label']} sign-in isn't set up on this server.")
        saved = unpack_state(request.cookies.get(COOKIE))
        if saved.get("p") != provider or not state or not hmac.compare_digest(state, saved.get("s", "")) or not code:
            raise OAuthError("Your sign-in couldn't be verified. Please try again.")
        claims = exchange_code(provider, code, saved["v"], redirect_uri(request, provider))
        check_claims(provider, claims, credentials(provider)[0], saved["n"])
        conn = connect()
        try:
            try:
                uid, username, created = find_or_create_user(conn, provider, claims)
            except IntegrityError:   # two first sign-ins at once: the other one won, so this is a repeat sign-in
                uid, username, created = find_or_create_user(conn, provider, claims)
        finally:
            conn.close()
    except OAuthError as e:
        return _back_to_app(request, error=str(e))
    return _back_to_app(request, token=make_token(uid), user_id=uid, username=username, new=int(created))
