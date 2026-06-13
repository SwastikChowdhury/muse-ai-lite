"""Persistence layer.

Two independent stores live here:
  - mongo.py: the chat transcript / whispers / flagged messages (MongoDB).
  - postgres.py + models_sql.py + crud.py: the auth schema (users + refresh
    tokens) on Postgres.

They are deliberately separate engines with no cross-store joins; the only link
is the user id used as a key on both sides.
"""
