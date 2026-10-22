"""Password hashing and sign-in tokens (standard library only).

Passwords: scrypt with a random per-user salt; only the hash is stored.
Tokens: "<user_id>.<HMAC-SHA256(APP_SECRET_KEY, user_id)>". They prove which
user is calling, so one user can't read or delete another's data by changing
the id in a URL. Deleting the account makes its token useless (user ids are
never reused). Minimal by design for a class project: no expiry or revocation.
"""

import hashlib
import hmac
import secrets

from fastapi import Header, HTTPException

from app.config import app_secret_key

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                                   dklen=len(digest) // 2)
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


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
