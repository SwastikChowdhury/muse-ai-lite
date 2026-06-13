"""Async SQLAlchemy engine, session factory, and declarative base for Postgres.

This is the relational counterpart to db.py (MongoDB). It owns the single
async engine/connection pool the auth layer uses and exposes:

  - engine            -> the AsyncEngine (one per process)
  - AsyncSessionLocal -> async session factory
  - Base              -> declarative base every ORM model inherits from
  - get_db()          -> FastAPI dependency yielding a session, always closed

POSTGRES_URI is read from the environment (e.g.
"postgresql+asyncpg://muse:muse@localhost:5432/muse"). The engine is created at
import time, but create_async_engine does NOT open a connection until first use,
so importing this module with a dummy URI (as tests do) is safe.
"""

import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

# No fallback default: in real runs this must point at a reachable Postgres, and
# tests set a dummy value via conftest. Failing loudly on a missing URI beats
# silently connecting somewhere unexpected.
POSTGRES_URI = os.environ["POSTGRES_URI"]

# echo=False keeps the logs clean; pool_pre_ping avoids handing out a stale
# connection after Postgres restarts (common in docker-compose dev loops).
engine = create_async_engine(POSTGRES_URI, echo=False, pool_pre_ping=True)

# expire_on_commit=False so objects returned from a request remain usable after
# the session commits (we frequently read attributes off a freshly created user
# to build the response).
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()


async def get_db():
    """FastAPI dependency: yield one AsyncSession per request, then close it.

    The session is closed in `finally` so the connection is returned to the pool
    whether the endpoint succeeds or raises. Endpoints own their own
    commit/rollback (the CRUD layer commits writes); this just manages lifetime.
    """
    async with AsyncSessionLocal() as session:
        yield session
