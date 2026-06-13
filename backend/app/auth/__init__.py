"""Authentication: password hashing, JWT/refresh tokens, Google OAuth, router.

Composes with the database/ package (users + refresh tokens) to provide the
/auth/* HTTP surface. No agent or chat logic lives here.
"""
