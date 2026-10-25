"""Sign in with Google / Microsoft (app/oauth.py): the find-or-create rules for both providers, the ID token checks,
and the whole redirect -> callback round trip (PKCE, state, nonce) with the provider's token endpoint faked.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_oauth.py -v
"""

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app import oauth
from app.db import connect
from app.oauth import MICROSOFT_CONSUMER_TENANT, OAuthError, check_claims, find_or_create_user, unpack_state

WORK_TENANT = "72f988bf-86f1-41af-91ab-2d7cd011db47"


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch):
    """Only the settings each test sets: never a real OAuth key from a local .env file."""
    from app import config
    monkeypatch.setattr(config, "ENV_PATHS", ())


def google(sub="g-1", email="sam.lee@gmail.com", verified=True, **extra):
    return {"iss": "https://accounts.google.com", "aud": "google-client", "sub": sub, "email": email,
            "email_verified": verified, "given_name": "Sam", "name": "Sam Lee", **extra}


def microsoft(sub="m-1", email="sam.lee@outlook.com", tid=MICROSOFT_CONSUMER_TENANT, **extra):
    return {"iss": f"https://login.microsoftonline.com/{tid}/v2.0", "aud": "ms-client", "tid": tid, "sub": sub,
            "email": email, "given_name": "Sam", "name": "Sam Lee", **extra}


def sign_in(provider, claims):
    conn = connect()
    try:
        return find_or_create_user(conn, provider, claims)
    finally:
        conn.close()


def user(uid):
    conn = connect()
    try:
        u = conn.execute("SELECT username, first_name, email, password_hash FROM users WHERE id = ?", (uid,)).fetchone()
        ids = [tuple(r) for r in conn.execute(
            "SELECT provider, subject, email_verified FROM oauth_identities WHERE user_id = ? ORDER BY provider", (uid,))]
        return {"username": str(u["username"]), "first_name": u["first_name"],
                "email": str(u["email"]) if u["email"] else None, "password_hash": u["password_hash"], "ids": ids}
    finally:
        conn.close()


def n_users():
    conn = connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------- find or create: Google

def test_google_first_sign_in_creates_an_account(test_db):
    uid, username, created = sign_in("google", google())
    assert created and username == "sam.lee"
    assert user(uid) == {"username": "sam.lee", "first_name": "Sam", "email": "sam.lee@gmail.com",
                         "password_hash": None, "ids": [("google", "g-1", 1)]}


def test_google_repeat_sign_in_is_the_same_account_even_if_the_email_changed(test_db):
    uid, _, _ = sign_in("google", google())
    again = sign_in("google", google(email="sam.new@gmail.com"))
    assert again == (uid, "sam.lee", False) and n_users() == 1


def test_google_verified_email_links_to_the_account_with_that_email(test_db):
    uid, _, _ = sign_in("microsoft", microsoft(email="sam@example.com"))    # verified (personal Microsoft account)
    linked = sign_in("google", google(email="SAM@example.com"))              # same address, any capitalization
    assert linked[0] == uid and linked[2] is False and n_users() == 1
    assert [p for p, *_ in user(uid)["ids"]] == ["google", "microsoft"]


def test_google_unverified_email_never_links_and_is_not_stored(test_db):
    uid, _, _ = sign_in("microsoft", microsoft(email="sam@example.com"))
    other, _, created = sign_in("google", google(sub="g-2", email="sam@example.com", verified=False))
    assert created and other != uid and n_users() == 2
    assert user(other)["email"] is None and user(other)["ids"] == [("google", "g-2", 0)]


def test_a_password_account_is_never_linked_by_its_username(test_db):
    """Accounts from before usernames have an email-looking username, but no verified email: a Google sign-in with
    that address gets its own account, never the password account."""
    conn = connect()
    with conn:
        old = conn.execute("INSERT INTO users (username, password_hash) VALUES ('sam.lee@gmail.com', 'x')").lastrowid
    conn.close()
    uid, username, created = sign_in("google", google())
    assert created and uid != old and username == "sam.lee"


def test_usernames_from_email_are_made_unique(test_db):
    a = sign_in("google", google(sub="a", email="sam.lee@gmail.com"))
    b = sign_in("google", google(sub="b", email="sam.lee@other.com"))
    c = sign_in("microsoft", microsoft(sub="c", email="sam.lee@outlook.com"))
    assert [a[1], b[1], c[1]] == ["sam.lee", "sam.lee.2", "sam.lee.3"]


def test_a_name_only_account_gets_a_sensible_username(test_db):
    _, username, _ = sign_in("google", google(sub="x", email=None, verified=False, given_name="Jo", name="Jo"))
    assert username == "beefit.Jo"


# ---------------------------------------------------------------- find or create: Microsoft

def test_microsoft_personal_account_creates_then_signs_in_again(test_db):
    uid, username, created = sign_in("microsoft", microsoft())
    assert created and username == "sam.lee" and user(uid)["email"] == "sam.lee@outlook.com"
    assert sign_in("microsoft", microsoft()) == (uid, "sam.lee", False)


def test_microsoft_work_account_email_is_not_trusted_for_linking(test_db):
    uid, _, _ = sign_in("google", google(email="sam@contoso.com"))
    other, _, created = sign_in("microsoft", microsoft(email="sam@contoso.com", tid=WORK_TENANT))
    assert created and other != uid and user(other)["email"] is None


def test_microsoft_work_account_with_a_domain_verified_email_links(test_db):
    uid, _, _ = sign_in("google", google(email="sam@contoso.com"))
    linked = sign_in("microsoft", microsoft(email="sam@contoso.com", tid=WORK_TENANT, xms_edov=True))
    assert linked[0] == uid and not linked[2]


def test_the_same_subject_at_the_other_provider_is_a_different_identity(test_db):
    a = sign_in("google", google(sub="same", email="a@gmail.com"))
    b = sign_in("microsoft", microsoft(sub="same", email="b@outlook.com"))
    assert a[0] != b[0]


def test_deleting_the_account_removes_its_sign_in_links(client):
    from app.security import make_token
    uid, _, _ = sign_in("google", google())
    r = client.delete(f"/api/users/{uid}", headers={"Authorization": f"Bearer {make_token(uid)}"})
    assert r.status_code == 200 and r.json()["rows_removed"]["oauth_identities"] == 1
    assert sign_in("google", google())[2] is True                          # signing in again starts fresh


# ---------------------------------------------------------------- the ID token checks

def test_claims_are_checked():
    now = time.time()
    ok = google(nonce="n1", exp=now + 600)
    check_claims("google", ok, "google-client", "n1", now)
    check_claims("microsoft", microsoft(nonce="n1", exp=now + 600), "ms-client", "n1", now)
    bad = [
        ("google", {**ok, "iss": "https://evil.example"}, "google-client"),
        ("google", {**ok, "aud": "someone-else"}, "google-client"),
        ("google", {**ok, "nonce": "replayed"}, "google-client"),
        ("google", {**ok, "exp": now - 3600}, "google-client"),
        ("google", {k: v for k, v in ok.items() if k != "sub"}, "google-client"),
        ("microsoft", {**microsoft(nonce="n1", exp=now + 600), "tid": WORK_TENANT}, "ms-client"),  # iss / tid mismatch
    ]
    for provider, claims, cid in bad:
        with pytest.raises(OAuthError):
            check_claims(provider, claims, cid, "n1", now)


def test_the_state_cookie_is_signed_and_expires(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    packed = oauth.pack_state({"s": "x", "t": int(time.time())})
    assert unpack_state(packed)["s"] == "x"
    payload, sig = packed.rsplit(".", 1)
    with pytest.raises(OAuthError):
        unpack_state(f"{payload}.{'0' * len(sig)}")                         # tampered
    with pytest.raises(OAuthError):
        unpack_state(None)                                                  # no cookie (another browser)
    with pytest.raises(OAuthError):
        unpack_state(oauth.pack_state({"s": "x", "t": int(time.time()) - 3600}))   # too old


# ---------------------------------------------------------------- the full round trip over HTTP

@pytest.fixture
def configured(monkeypatch):
    for k, v in {"GOOGLE_CLIENT_ID": "google-client", "GOOGLE_CLIENT_SECRET": "g-secret",
                 "MICROSOFT_CLIENT_ID": "ms-client", "MICROSOFT_CLIENT_SECRET": "m-secret",
                 "PUBLIC_BASE_URL": "http://testserver"}.items():
        monkeypatch.setenv(k, v)


def fake_provider(monkeypatch, claims_for):
    """Stand-in for the provider's token endpoint. Checks what a real one checks (the PKCE verifier matches the
    challenge from /start, the same redirect URI), then returns an ID token with the claims."""
    seen = {}

    def post(url, data, timeout):
        seen.update(url=url, data=data)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=")
        if data["code"] != "good-code" or challenge.decode() != seen["challenge"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        body = base64.urlsafe_b64encode(json.dumps(claims_for(seen)).encode()).rstrip(b"=").decode()
        return httpx.Response(200, json={"id_token": f"e30.{body}.sig", "access_token": "a"})
    monkeypatch.setattr(oauth.httpx, "post", post)
    return seen


def start(client, provider, seen=None):
    r = client.get(f"/api/auth/{provider}/start", follow_redirects=False)
    assert r.status_code == 302
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    if seen is not None:
        seen["challenge"], seen["nonce"] = q["code_challenge"], q["nonce"]
    return r, q


def fragment(r):
    loc = urlsplit(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == "http://testserver/auth/callback"
    return {k: v[0] for k, v in parse_qs(loc.fragment).items()}


def test_providers_endpoint_says_which_buttons_to_show(client, monkeypatch):
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"):
        monkeypatch.setenv(k, "")
    assert client.get("/api/auth/providers").json() == {"google": False, "microsoft": False}
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    assert client.get("/api/auth/providers").json() == {"google": True, "microsoft": False}
    assert client.get("/api/auth/facebook/start", follow_redirects=False).status_code == 404


@pytest.mark.parametrize("provider, host", [("google", "accounts.google.com"),
                                            ("microsoft", "login.microsoftonline.com")])
def test_start_redirects_with_pkce_state_and_nonce(client, configured, provider, host):
    r, q = start(client, provider)
    assert urlsplit(r.headers["location"]).netloc == host
    assert q["redirect_uri"] == f"http://testserver/api/auth/{provider}/callback"     # PUBLIC_BASE_URL + the route
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["response_type"] == "code" and q["scope"] == "openid email profile"
    assert len(q["state"]) >= 32 and len(q["nonce"]) >= 32 and q["state"] != q["nonce"]
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower() and "Path=/api/auth" in cookie
    saved = unpack_state(client.cookies["bf_oauth"])
    assert (saved["p"], saved["s"], saved["n"]) == (provider, q["state"], q["nonce"])
    assert "code_verifier" not in r.headers["location"] and saved["v"] not in r.headers["location"]


def test_the_state_cookie_is_secure_on_https(client, configured, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://bee-fit.onrender.com")
    r = client.get("/api/auth/google/start", follow_redirects=False)
    assert "Secure" in r.headers["set-cookie"]
    q = parse_qs(urlsplit(r.headers["location"]).query)
    assert q["redirect_uri"] == ["https://bee-fit.onrender.com/api/auth/google/callback"]


@pytest.mark.parametrize("provider, claims", [("google", google), ("microsoft", microsoft)])
def test_full_round_trip_signs_in_with_the_same_session_as_a_password(client, configured, monkeypatch, provider,
                                                                      claims):
    seen = fake_provider(monkeypatch, lambda s: claims(nonce=s["nonce"], exp=time.time() + 600))
    _, q = start(client, provider, seen)
    r = client.get(f"/api/auth/{provider}/callback", params={"code": "good-code", "state": q["state"]},
                   follow_redirects=False)
    f = fragment(r)
    assert set(f) == {"token", "user_id", "username", "new"} and f["new"] == "1" and f["username"] == "sam.lee"
    assert seen["data"]["redirect_uri"] == f"http://testserver/api/auth/{provider}/callback"
    assert 'bf_oauth=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]   # used up
    me = client.get(f"/api/users/{f['user_id']}", headers={"Authorization": f"Bearer {f['token']}"}).json()
    assert me["username"] == "sam.lee" and me["sign_in_with"] == [provider] and me["has_password"] is False

    _, q = start(client, provider, seen)                                    # the second time: same account
    f2 = fragment(client.get(f"/api/auth/{provider}/callback", params={"code": "good-code", "state": q["state"]},
                             follow_redirects=False))
    assert (f2["user_id"], f2["new"], f2["token"]) == (f["user_id"], "0", f["token"])


def test_a_wrong_state_is_refused_and_nobody_is_signed_in(client, configured, monkeypatch):
    seen = fake_provider(monkeypatch, lambda s: google(nonce=s["nonce"], exp=time.time() + 600))
    start(client, "google", seen)
    f = fragment(client.get("/api/auth/google/callback", params={"code": "good-code", "state": "forged"},
                            follow_redirects=False))
    assert set(f) == {"error"} and "couldn't be verified" in f["error"]
    assert "url" not in seen and n_users() == 0                              # the code was never even exchanged


def test_a_callback_without_the_cookie_is_refused(client, configured, monkeypatch):
    seen = fake_provider(monkeypatch, lambda s: google(nonce=s["nonce"], exp=time.time() + 600))
    _, q = start(client, "google", seen)
    client.cookies.clear()                                                  # e.g. the link opened in another browser
    f = fragment(client.get("/api/auth/google/callback", params={"code": "good-code", "state": q["state"]},
                            follow_redirects=False))
    assert "error" in f and n_users() == 0


def test_a_replayed_id_token_is_refused(client, configured, monkeypatch):
    seen = fake_provider(monkeypatch, lambda s: google(nonce="an-old-nonce", exp=time.time() + 600))
    _, q = start(client, "google", seen)
    f = fragment(client.get("/api/auth/google/callback", params={"code": "good-code", "state": q["state"]},
                            follow_redirects=False))
    assert "error" in f and n_users() == 0


def test_a_rejected_code_and_a_cancel_come_back_as_messages(client, configured, monkeypatch):
    seen = fake_provider(monkeypatch, lambda s: google(nonce=s["nonce"], exp=time.time() + 600))
    _, q = start(client, "google", seen)
    f = fragment(client.get("/api/auth/google/callback", params={"code": "bad-code", "state": q["state"]},
                            follow_redirects=False))
    assert f == {"error": "Google didn't accept the sign-in. Please try again."}
    f = fragment(client.get("/api/auth/microsoft/callback", params={"error": "access_denied"}, follow_redirects=False))
    assert f == {"error": "Microsoft sign-in was cancelled."}
    assert n_users() == 0


def test_an_oauth_only_account_cannot_sign_in_with_a_password(client):
    uid, username, _ = sign_in("google", google())
    r = client.post("/api/login", json={"username": username, "password": "anything at all"})
    assert r.status_code == 401


def test_starting_oauth_is_rate_limited(client, configured):
    codes = [client.get("/api/auth/google/start", follow_redirects=False).status_code for _ in range(21)]
    assert codes[:20] == [302] * 20 and codes[20] == 429
