"""Password hashing using bcrypt.

Centralizes the one hashing scheme so the rest of the codebase never touches
bcrypt directly. bcrypt automatically salts each hash, so equal passwords still
produce different stored values, and the salt/cost is embedded in the hash
string itself (no separate column needed).

Uses the `bcrypt` package directly rather than passlib, which is incompatible
with bcrypt 4.x+ in current passlib releases.
"""

import bcrypt


def hash_password(plain: str) -> str:
    """Return a salted bcrypt hash of `plain`, safe to store in Postgres."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff `plain` matches the stored bcrypt `hashed` value."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
