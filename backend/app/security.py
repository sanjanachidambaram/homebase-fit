"""Password hashing, sign-in tokens, and rate limits.

Passwords: Argon2id via pwdlib (since 2026-10-25), with a random per-user salt; only the hash is stored. Hashes made
before that are scrypt ("scrypt$n$r$p$salt$digest"): they still verify, and verify_and_update() hands back an Argon2
replacement so the account is upgraded the first time its owner signs in (app/users.py login).
Tokens: "<user_id>.<HMAC-SHA256(APP_SECRET_KEY, user_id)>". They prove which user is calling, so one user can't read
or delete another's data by changing the id in a URL. Deleting the account makes its token useless (user ids are never
reused). The same token is issued after a password sign-in and after Google / Microsoft sign-in (app/oauth.py).
Minimal by design for a class project: no expiry or revocation.
Rate limits (slowapi, per client IP): sign-in, sign-up and the OAuth start routes, so passwords can't be guessed in
bulk and accounts can't be mass-created. The limits are in-memory, which fits one service instance.
"""

import hashlib
import hmac

from fastapi import Header, HTTPException
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import app_secret_key

_argon2 = PasswordHash((Argon2Hasher(),))

LOGIN_LIMIT = "10/minute"     # per IP: plenty for typos, far too few to guess passwords
SIGNUP_LIMIT = "5/minute"
OAUTH_LIMIT = "20/minute"
limiter = Limiter(key_func=get_remote_address)


def hash_password(password: str) -> str:
    return _argon2.hash(password)


def _verify_scrypt(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                                   dklen=len(digest) // 2)
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


def verify_and_update(password: str, stored: str | None) -> tuple[bool, str | None]:
    """(matches, a new hash to store or None). The new hash is set when an old scrypt hash matched (upgrade it to
    Argon2) or when Argon2's own settings have changed. An account with no password (Google / Microsoft only) never
    matches."""
    if not stored:
        return False, None
    if stored.startswith("scrypt$"):
        return (True, hash_password(password)) if _verify_scrypt(password, stored) else (False, None)
    try:
        return _argon2.verify_and_update(password, stored)
    except Exception:   # a malformed hash: treat it as a wrong password, never a 500
        return False, None


def verify_password(password: str, stored: str | None) -> bool:
    return verify_and_update(password, stored)[0]


def _sign(user_id: int) -> str:
    return hmac.new(app_secret_key().encode(), str(user_id).encode(), hashlib.sha256).hexdigest()


def make_token(user_id: int) -> str:
    return f"{user_id}.{_sign(user_id)}"


def token_user_id(authorization: str | None = Header(None)) -> int:
    """FastAPI dependency: the user id from a valid "Authorization: Bearer <token>" header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in first.")
    user_part, _, sig = authorization.removeprefix("Bearer ").partition(".")
    if not user_part.isdigit() or not hmac.compare_digest(sig, _sign(int(user_part))):
        raise HTTPException(401, "Your sign-in is invalid or expired. Please sign in again.")
    return int(user_part)


def require_same_user(path_user_id: int, token_uid: int) -> None:
    if path_user_id != token_uid:
        raise HTTPException(403, "You can only access your own account.")
