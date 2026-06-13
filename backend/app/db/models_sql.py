"""SQLAlchemy ORM models for the auth schema (Postgres).

Two tables:
  - users          -> one row per account (email/password and/or Google OAuth)
  - refresh_tokens -> opaque refresh tokens, one user to many, cascade-deleted
                      with the user

UUID primary keys are generated server-side (gen_random_uuid()) so the database
owns identity and we never have to coordinate id allocation in the app. Times
are stored as timezone-aware UTC.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.postgres import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used as the Python-side default for created_at."""
    return datetime.now(timezone.utc)


class User(Base):
    """An account. Either or both auth methods may be present:

    - email/password: `hashed_password` set, `google_oauth_id` null
    - Google OAuth:   `google_oauth_id` set, `hashed_password` may be null

    `email` is unique and indexed because it's the login lookup key.
    `hashed_password` is NEVER serialized into any API response.
    """

    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=True)  # null for Google-only users
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    dob = Column(Date, nullable=False)
    location = Column(String, nullable=True)
    nationality = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    is_verified = Column(Boolean, nullable=False, default=False, server_default="false")
    # null for email/password-only users; set to Google's stable subject id.
    google_oauth_id = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    refresh_tokens = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RefreshToken(Base):
    """A stored refresh token (opaque random string, not a JWT).

    Persisting refresh tokens lets us revoke them (logout) and rotate them on
    every /auth/refresh. Deleting a user cascades to their tokens via the FK's
    ON DELETE CASCADE.
    """

    __tablename__ = "refresh_tokens"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    user = relationship("User", back_populates="refresh_tokens")
