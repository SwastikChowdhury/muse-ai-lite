"""JWT access tokens + opaque refresh tokens.

Two distinct token types with different lifetimes and storage:

  - Access token: a short-lived signed JWT carrying the user id. Stateless —
    verified by signature alone, never stored server-side. Used as the bearer
    credential on /auth/me and the /ws connection.
  - Refresh token: a long-lived opaque random string (NOT a JWT). It carries no
    claims and is only meaningful because a matching row exists in Postgres, so
    it can be revoked (logout) and rotated. This module only mints the value and
    computes its expiry; persistence lives in database.crud.

Config is read from the environment at import:
  JWT_SECRET, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS

Note: `from jose import jwt` is an absolute import, so this module being named
jwt.py does not shadow the library.
"""

import os
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7"))


def create_access_token(user_id: str) -> str:
    """Mint a signed access JWT for `user_id`.

    Payload: {"sub": <user_id>, "type": "access", "exp": <utc expiry>}. The
    "type" claim lets verify_access_token reject a refresh/other token that was
    somehow presented as an access token.
    """
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "type": "access", "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token() -> str:
    """Generate a cryptographically secure opaque refresh token.

    Not a JWT — just a high-entropy URL-safe string. Its validity comes entirely
    from the matching row stored in Postgres.
    """
    return secrets.token_urlsafe(32)


def verify_access_token(token: str) -> str | None:
    """Return the user id from a valid access token, or None on any failure.

    Returns None (rather than raising) for expired, malformed, wrong-type, or
    badly-signed tokens so callers can uniformly treat "no valid identity" as a
    single case (HTTP 401 / websocket close).
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "access":
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    return user_id


def get_refresh_token_expiry() -> datetime:
    """Return the UTC expiry for a newly minted refresh token."""
    return datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
