"""Security primitives: roles & permissions (RBAC), password hashing, password policy and JWT.

* Passwords: PBKDF2-HMAC-SHA256 (stdlib), per-user 128-bit salt, iteration count stored in the
  hash string so it can be raised later (hashes are upgraded transparently on the next login).
* Access tokens: HS256-signed JWTs with iss/aud/sub/sid/exp/iat/nbf/jti claims. The algorithm is
  pinned on decode (no ``alg=none`` / algorithm-confusion), and every token is bound to a
  server-side session (``sid``) so it can be revoked before it expires.
* RBAC: a role -> permission map plus a role -> analysable-dimension map; both are enforced in
  the backend (routes and the analysis planner), never only in the UI.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import jwt

from ..config import get_settings
from .errors import AuthenticationError, AuthorizationError


class Role(str, Enum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


# Dimensions each role may group or filter by (enforced in the backend planner/analysis layer).
ROLE_DIMENSIONS: dict[Role, frozenset[str]] = {
    Role.ADMIN: frozenset({"bank", "merchant", "merchant_category", "region", "payment_method", "failure_code", "day"}),
    Role.ANALYST: frozenset({"bank", "merchant", "merchant_category", "region", "payment_method", "failure_code", "day"}),
    Role.VIEWER: frozenset({"merchant_category", "region", "payment_method", "failure_code", "day"}),
}

ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.ADMIN: frozenset({"analytics", "dashboard", "quality", "reconciliation", "scenarios:activate", "sql:sandbox",
                           "history", "users:manage", "audit:read", "account"}),
    Role.ANALYST: frozenset({"analytics", "dashboard", "history", "sql:validate", "account"}),
    Role.VIEWER: frozenset({"analytics", "dashboard", "history", "account"}),
}

# Least privilege: self-registered accounts start as VIEWER; an ADMIN can promote them.
SIGNUP_DEFAULT_ROLE = Role.VIEWER

DEMO_USERS = [
    ("admin@payinsight.demo", "Asha Admin", Role.ADMIN),
    ("analyst@payinsight.demo", "Arjun Analyst", Role.ANALYST),
    ("viewer@payinsight.demo", "Vera Viewer", Role.VIEWER),
]


@dataclass(frozen=True)
class User:
    user_id: int
    email: str
    full_name: str
    role: Role
    session_id: str | None = None

    @property
    def allowed_dimensions(self) -> frozenset[str]:
        return ROLE_DIMENSIONS[self.role]

    @property
    def permissions(self) -> frozenset[str]:
        return ROLE_PERMISSIONS[self.role]

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS[self.role]

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise AuthorizationError(
                f"Role {self.role.value} is not permitted to perform '{permission}'.",
                details={"role": self.role.value, "required_permission": permission},
            )


# ---------------------------------------------------------------- time helpers
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Fixed-width ISO-8601 UTC string so lexical comparison in SQL equals time comparison."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


# ---------------------------------------------------------------- passwords
def hash_password(password: str, *, iterations: int | None = None, salt: bytes | None = None) -> str:
    iterations = iterations or get_settings().password_hash_iterations
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, digest_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def needs_rehash(stored: str) -> bool:
    try:
        return int(stored.split("$")[1]) != get_settings().password_hash_iterations
    except (IndexError, ValueError):
        return True


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """Verified against when the email is unknown, so response time does not reveal which emails exist."""
    return hash_password(secrets.token_urlsafe(16))


_COMMON = {"password", "password1", "123456789", "1234567890", "qwerty123", "qwertyuiop", "letmein", "welcome1",
           "iloveyou", "admin123", "abc12345", "passw0rd"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def password_problems(password: str, email: str = "") -> list[str]:
    """Return the list of unmet password-policy rules (empty list = acceptable)."""
    problems: list[str] = []
    if len(password) < 10:
        problems.append("Use at least 10 characters.")
    if len(password) > 128:
        problems.append("Use at most 128 characters.")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        problems.append("Use at least 3 of: lowercase, uppercase, digit, symbol.")
    if password.lower() in _COMMON:
        problems.append("This password is too common.")
    local = email.split("@")[0].lower() if email else ""
    if len(local) >= 3 and local in password.lower():
        problems.append("Do not include your email name in the password.")
    return problems


def normalise_email(email: str) -> str:
    return email.strip().lower()


# ---------------------------------------------------------------- opaque tokens
def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)  # 384 bits


def token_hash(token: str) -> str:
    """Refresh tokens are stored only as SHA-256 hashes (they are high-entropy, so no salt is needed)."""
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------- JWT
JWT_ALGORITHM = "HS256"


@lru_cache(maxsize=4)
def _secret_for(path: str, configured: str | None) -> str:
    if configured:
        if len(configured) < 32:
            raise RuntimeError("PAYINSIGHT_JWT_SECRET must be at least 32 characters.")
        return configured
    p = Path(path)
    if p.exists():
        value = p.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    value = secrets.token_hex(32)
    p.write_text(value, encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:  # Windows ignores POSIX modes
        pass
    return value


def jwt_secret() -> str:
    s = get_settings()
    return _secret_for(str(s.jwt_secret_path), s.jwt_secret)


def create_access_token(*, user_id: int, session_id: str, role: str, email: str) -> tuple[str, int]:
    s = get_settings()
    now = utcnow()
    ttl = timedelta(minutes=s.access_token_ttl_minutes)
    claims = {
        "iss": s.jwt_issuer, "aud": s.jwt_audience, "sub": str(user_id), "sid": session_id,
        "role": role, "email": email, "typ": "access", "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()), "nbf": int(now.timestamp()), "exp": int((now + ttl).timestamp()),
    }
    return jwt.encode(claims, jwt_secret(), algorithm=JWT_ALGORITHM), int(ttl.total_seconds())


def decode_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        claims = jwt.decode(
            token, jwt_secret(), algorithms=[JWT_ALGORITHM], audience=s.jwt_audience, issuer=s.jwt_issuer,
            options={"require": ["exp", "iat", "nbf", "sub", "sid", "iss", "aud"]}, leeway=5,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Access token expired.", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Invalid access token.", code="TOKEN_INVALID",
                                  details={"reason": type(exc).__name__}) from exc
    if claims.get("typ") != "access":
        raise AuthenticationError("Invalid access token.", code="TOKEN_INVALID", details={"reason": "wrong token type"})
    return claims
