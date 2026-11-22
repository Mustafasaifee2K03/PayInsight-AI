"""Authentication & session management backed by the application database (data/app.db).

Model
-----
* **Access token**: short-lived JWT (default 15 min) sent as ``Authorization: Bearer``.
* **Refresh token**: 384-bit opaque random value in an httpOnly, SameSite=Strict cookie; only its
  SHA-256 hash is stored, in ``auth_sessions``. Every refresh **rotates** it.
* **Reuse detection**: presenting an already-rotated refresh token (outside a 5 s grace window for
  concurrent tabs) revokes the whole session, because it indicates the token was stolen.
* **Stateful check**: every authenticated request verifies the JWT signature/claims *and* that its
  session (``sid``) is still active and the user still enabled. Role is read from the database, so
  revocation, deactivation and role changes take effect immediately, not when the JWT expires.
* **Brute force**: per-account lockout after N consecutive failures, plus a per-IP rate limit on
  login/signup/refresh. Unknown emails still pay the password-hash cost (no timing oracle).
* **Audit**: every auth event (success or failure) is written to ``auth_audit_log``.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..config import get_settings
from ..core.errors import AuthenticationError, AuthorizationError, ConflictError, NotFoundError, RateLimitError, AppError
from ..core.security import (DEMO_USERS, EMAIL_RE, SIGNUP_DEFAULT_ROLE, Role, User, create_access_token, decode_access_token,
                             dummy_hash, hash_password, iso, needs_rehash, new_refresh_token, normalise_email,
                             password_problems, token_hash, utcnow, verify_password)
from ..core.ratelimit import RateLimiter as _RateLimiter, create_backend
from ..database.app_store import app_conn as _raw_conn, get_setting, set_setting


@contextmanager
def app_conn():
    """Like the store connection, but also commits when an AppError is raised, so that failure
    side effects (audit rows, failed-login counters, revocations) persist with the error response."""
    with _raw_conn() as c:
        try:
            yield c
        except AppError:
            c.commit()
            raise

REUSE_GRACE_SECONDS = 5
LAST_USED_WRITE_INTERVAL_S = 60


@dataclass(frozen=True)
class ClientInfo:
    ip: str = "unknown"
    user_agent: str = ""


@dataclass(frozen=True)
class AuthResult:
    access_token: str
    expires_in: int
    refresh_token: str
    user: User


class WeakPasswordError(AppError):
    status_code = 422
    code = "WEAK_PASSWORD"


# ---------------------------------------------------------------- rate limiting (pluggable backend, see core/ratelimit.py)
RateLimiter = _RateLimiter  # re-exported for callers/tests
limiter = _RateLimiter(create_backend(get_settings().rate_limit_backend))


def _rate_limit(bucket: str, client: ClientInfo) -> None:
    limiter.check(bucket, client.ip, get_settings().auth_rate_limit_per_minute)


# ---------------------------------------------------------------- audit
def audit(c: sqlite3.Connection, event: str, outcome: str, *, user_id: int | None = None, email: str | None = None,
          session_id: str | None = None, ip: str | None = None, detail: dict | str | None = None) -> None:
    c.execute(
        "INSERT INTO auth_audit_log(occurred_at, event_type, outcome, user_id, email, session_id, ip_address, detail) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (iso(utcnow()), event, outcome, user_id, email, session_id, ip,
         json.dumps(detail) if isinstance(detail, dict) else detail),
    )


def _user(row: sqlite3.Row, session_id: str | None = None) -> User:
    return User(row["user_id"], row["email"], row["full_name"], Role(row["role"]), session_id)


# ---------------------------------------------------------------- password-attempt budget (hardening iterations 4-5)
def _locked_error(retry_s: int) -> RateLimitError:
    return RateLimitError(f"Account temporarily locked after repeated failed sign-ins. Try again in {max(1, retry_s // 60)} min.",
                          code="ACCOUNT_LOCKED", details={"retry_after_seconds": retry_s}, headers={"Retry-After": str(retry_s)})


def _reserve_attempt(c: sqlite3.Connection, user_id: int, now: datetime) -> int | None:
    """Atomically claim one password-verification slot *before* the (slow) hash check.

    Returns the attempt number (1..max) or None if the account is locked / out of slots. Because the
    check-and-increment is a single conditional UPDATE committed immediately, N parallel guesses can
    no longer all pass a "not locked yet" read and all be evaluated (the race found in iteration 4)."""
    s = get_settings()
    row = c.execute(
        "UPDATE users SET failed_logins = failed_logins + 1, "
        "locked_until = CASE WHEN locked_until IS NOT NULL AND locked_until <= ? THEN NULL ELSE locked_until END "
        "WHERE user_id = ? AND (locked_until IS NULL OR locked_until <= ?) AND failed_logins < ? RETURNING failed_logins",
        (iso(now), user_id, iso(now), s.max_failed_logins)).fetchone()
    c.commit()
    return row[0] if row else None


def _lock_retry_seconds(c: sqlite3.Connection, user_id: int, now: datetime) -> int:
    r = c.execute("SELECT locked_until FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if r and r[0] and r[0] > iso(now):
        return int((datetime.fromisoformat(r[0]) - now).total_seconds()) + 1
    # Slots exhausted but no lock recorded (attempts still in flight, or one died mid-request): convert it into a
    # normal, expiring lock so the account can never be stuck in a permanent "no slots" state.
    minutes = get_settings().lockout_minutes
    c.execute("UPDATE users SET locked_until = ?, failed_logins = 0 WHERE user_id = ? AND (locked_until IS NULL OR locked_until <= ?)",
              (iso(now + timedelta(minutes=minutes)), user_id, iso(now)))
    c.commit()
    return minutes * 60


def _attempt_failed(c: sqlite3.Connection, user_id: int, attempt: int, now: datetime) -> datetime | None:
    """The attempt that consumed the last slot locks the account. Returns the lock expiry if it did."""
    s = get_settings()
    if attempt < s.max_failed_logins:
        return None
    until = now + timedelta(minutes=s.lockout_minutes)
    c.execute("UPDATE users SET failed_logins = 0, locked_until = ? WHERE user_id = ?", (iso(until), user_id))
    return until


def _attempt_succeeded(c: sqlite3.Connection, user_id: int) -> None:
    c.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE user_id = ?", (user_id,))
    c.commit()  # short transaction: never hold the app.db write lock across a password hash


# ---------------------------------------------------------------- seeding
def seed_demo_users() -> None:
    """Create the three documented demo accounts (and re-hash them if PAYINSIGHT_DEMO_PASSWORD changed)."""
    s = get_settings()
    fingerprint = token_hash(f"{s.demo_password}|{s.password_hash_iterations}")
    with app_conn() as c:
        existing = {r["email"] for r in c.execute("SELECT email FROM users")}
        stale = get_setting("demo_password_fp") != fingerprint
        for email, name, role in DEMO_USERS:
            if email not in existing:
                c.execute("INSERT INTO users(email, full_name, role, password_hash, created_at, password_changed_at) "
                          "VALUES (?,?,?,?,?,?)", (email, name, role.value, hash_password(s.demo_password), iso(utcnow()), iso(utcnow())))
            elif stale:
                c.execute("UPDATE users SET password_hash = ?, failed_logins = 0, locked_until = NULL WHERE email = ?",
                          (hash_password(s.demo_password), email))
    set_setting("demo_password_fp", fingerprint)


# ---------------------------------------------------------------- housekeeping (hardening iteration 10)
_housekeeping_lock = threading.Lock()
_last_housekeeping = 0.0


def housekeeping(c: sqlite3.Connection, now: datetime, *, force: bool = False) -> bool:
    """Purge sessions expired > 30 days ago and audit rows past retention, at most once per interval.

    Previously the session purge ran (as a full table scan) inside every login and signup, and the audit
    log grew without bound."""
    global _last_housekeeping
    s = get_settings()
    with _housekeeping_lock:
        if not force and time.monotonic() - _last_housekeeping < s.housekeeping_interval_seconds:
            return False
        _last_housekeeping = time.monotonic()
    c.execute("DELETE FROM auth_sessions WHERE expires_at < ?", (iso(now - timedelta(days=30)),))
    c.execute("DELETE FROM auth_audit_log WHERE occurred_at < ?", (iso(now - timedelta(days=s.audit_retention_days)),))
    return True



def startup_housekeeping() -> None:
    with app_conn() as c:
        housekeeping(c, utcnow(), force=True)

# ---------------------------------------------------------------- sessions
def _issue_session(c: sqlite3.Connection, row: sqlite3.Row, client: ClientInfo) -> AuthResult:
    s = get_settings()
    now = utcnow()
    sid = uuid.uuid4().hex
    refresh = new_refresh_token()
    c.execute(
        "INSERT INTO auth_sessions(session_id, user_id, refresh_token_hash, created_at, last_used_at, expires_at, user_agent, ip_address) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (sid, row["user_id"], token_hash(refresh), iso(now), iso(now), iso(now + timedelta(days=s.refresh_token_ttl_days)),
         client.user_agent[:250], client.ip),
    )
    housekeeping(c, now)
    access, ttl = create_access_token(user_id=row["user_id"], session_id=sid, role=row["role"], email=row["email"])
    return AuthResult(access, ttl, refresh, _user(row, sid))


def signup(email: str, full_name: str, password: str, client: ClientInfo) -> AuthResult:
    s = get_settings()
    _rate_limit("signup", client)
    if not s.allow_signup:
        raise AuthorizationError("Self-registration is disabled.", code="SIGNUP_DISABLED")
    email = normalise_email(email)
    full_name = " ".join(full_name.split())
    if not EMAIL_RE.match(email):
        raise AppError("Enter a valid email address.", code="INVALID_EMAIL", status_code=422)
    if len(full_name) < 2:
        raise AppError("Enter your full name.", code="INVALID_NAME", status_code=422)
    problems = password_problems(password, email)
    if problems:
        raise WeakPasswordError("Password does not meet the policy.", details={"problems": problems})
    with app_conn() as c:
        if c.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            audit(c, "SIGNUP", "FAILURE", email=email, ip=client.ip, detail="email already registered")
            raise ConflictError("An account with this email already exists.", code="EMAIL_TAKEN")
        now = iso(utcnow())
        cur = c.execute(
            "INSERT INTO users(email, full_name, role, password_hash, created_at, password_changed_at, last_login_at) "
            "VALUES (?,?,?,?,?,?,?)", (email, full_name, SIGNUP_DEFAULT_ROLE.value, hash_password(password), now, now, now))
        row = c.execute("SELECT * FROM users WHERE user_id = ?", (cur.lastrowid,)).fetchone()
        result = _issue_session(c, row, client)
        audit(c, "SIGNUP", "SUCCESS", user_id=row["user_id"], email=email, session_id=result.user.session_id, ip=client.ip,
              detail={"role": SIGNUP_DEFAULT_ROLE.value})
        return result


def login(email: str, password: str, client: ClientInfo) -> AuthResult:
    s = get_settings()
    _rate_limit("login", client)
    email = normalise_email(email)
    now = utcnow()
    with app_conn() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            verify_password(password, dummy_hash())  # equalise timing
            audit(c, "LOGIN", "FAILURE", email=email, ip=client.ip, detail="unknown email")
            raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS")
        attempt = _reserve_attempt(c, row["user_id"], now)
        if attempt is None:
            retry = _lock_retry_seconds(c, row["user_id"], now)
            verify_password(password, dummy_hash())  # constant work: do not reveal the lock via timing either
            audit(c, "LOGIN", "FAILURE", user_id=row["user_id"], email=email, ip=client.ip, detail="account locked")
            raise _locked_error(retry)
        if not verify_password(password, row["password_hash"]):
            until = _attempt_failed(c, row["user_id"], attempt, now)
            if until:
                audit(c, "ACCOUNT_LOCKED", "FAILURE", user_id=row["user_id"], email=email, ip=client.ip,
                      detail={"failed_attempts": attempt, "locked_until": iso(until)})
                c.commit()
                raise RateLimitError(f"Too many failed sign-ins. Account locked for {s.lockout_minutes} minutes.",
                                     code="ACCOUNT_LOCKED", details={"retry_after_seconds": s.lockout_minutes * 60},
                                     headers={"Retry-After": str(s.lockout_minutes * 60)})
            audit(c, "LOGIN", "FAILURE", user_id=row["user_id"], email=email, ip=client.ip, detail="wrong password")
            c.commit()
            raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS",
                                      details={"attempts_remaining": s.max_failed_logins - attempt})
        _attempt_succeeded(c, row["user_id"])
        if not row["is_active"]:
            audit(c, "LOGIN", "FAILURE", user_id=row["user_id"], email=email, ip=client.ip, detail="account disabled")
            raise AuthorizationError("This account has been disabled by an administrator.", code="ACCOUNT_DISABLED")
        updates = {"failed_logins": 0, "locked_until": None, "last_login_at": iso(now)}
        if needs_rehash(row["password_hash"]):
            updates["password_hash"] = hash_password(password)
        c.execute(f"UPDATE users SET {', '.join(f'{k} = ?' for k in updates)} WHERE user_id = ?", (*updates.values(), row["user_id"]))
        row = c.execute("SELECT * FROM users WHERE user_id = ?", (row["user_id"],)).fetchone()
        result = _issue_session(c, row, client)
        audit(c, "LOGIN", "SUCCESS", user_id=row["user_id"], email=email, session_id=result.user.session_id, ip=client.ip)
        return result


def refresh(refresh_token: str | None, client: ClientInfo) -> AuthResult:
    _rate_limit("refresh", client)
    if not refresh_token:
        raise AuthenticationError("No active session. Please sign in.", code="REFRESH_MISSING")
    h = token_hash(refresh_token)
    now = utcnow()
    with app_conn() as c:
        sess = c.execute("SELECT * FROM auth_sessions WHERE refresh_token_hash = ?", (h,)).fetchone()
        if sess is None:
            old = c.execute("SELECT * FROM auth_sessions WHERE previous_refresh_hash = ?", (h,)).fetchone()
            if old is None:
                raise AuthenticationError("Session not recognised. Please sign in.", code="REFRESH_INVALID")
            # grace is measured from the moment of rotation (not last API use, which any request bumps)
            rotated_ago = (now - datetime.fromisoformat(old["rotated_at"])).total_seconds() if old["rotated_at"] else float("inf")
            if old["revoked_at"] is None and rotated_ago <= REUSE_GRACE_SECONDS:
                # benign race between two tabs: the browser already holds the newer cookie
                raise AuthenticationError("Session was just refreshed; retry.", code="REFRESH_SUPERSEDED")
            c.execute("UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, ?), revoke_reason = COALESCE(revoke_reason, ?) "
                      "WHERE session_id = ?", (iso(now), "refresh_token_reuse", old["session_id"]))
            audit(c, "REFRESH_TOKEN_REUSE", "FAILURE", user_id=old["user_id"], session_id=old["session_id"], ip=client.ip,
                  detail="rotated refresh token presented again; session revoked")
            c.commit()
            raise AuthenticationError("Session revoked for security reasons. Please sign in again.", code="REFRESH_TOKEN_REUSED")
        if sess["revoked_at"]:
            raise AuthenticationError("Session has been signed out. Please sign in again.", code="SESSION_REVOKED")
        if sess["expires_at"] < iso(now):
            raise AuthenticationError("Session expired. Please sign in again.", code="SESSION_EXPIRED")
        row = c.execute("SELECT * FROM users WHERE user_id = ?", (sess["user_id"],)).fetchone()
        if row is None or not row["is_active"]:
            c.execute("UPDATE auth_sessions SET revoked_at = ?, revoke_reason = 'account_disabled' WHERE session_id = ?",
                      (iso(now), sess["session_id"]))
            c.commit()
            raise AuthenticationError("Account disabled.", code="ACCOUNT_DISABLED")
        new_refresh = new_refresh_token()
        # Compare-and-swap (hardening iteration 2): only the request that still sees the presented hash as current
        # may rotate it. Previously N concurrent refreshes with one token could all succeed, minting N live tokens.
        cur = c.execute("UPDATE auth_sessions SET refresh_token_hash = ?, previous_refresh_hash = ?, rotation_count = rotation_count + 1, "
                        "last_used_at = ?, rotated_at = ?, ip_address = ?, user_agent = ? "
                        "WHERE session_id = ? AND refresh_token_hash = ? AND revoked_at IS NULL",
                        (token_hash(new_refresh), h, iso(now), iso(now), client.ip, client.user_agent[:250] or sess["user_agent"],
                         sess["session_id"], h))
        if cur.rowcount != 1:
            raise AuthenticationError("Session was just refreshed; retry.", code="REFRESH_SUPERSEDED")
        access, ttl = create_access_token(user_id=row["user_id"], session_id=sess["session_id"], role=row["role"], email=row["email"])
        audit(c, "TOKEN_REFRESH", "SUCCESS", user_id=row["user_id"], session_id=sess["session_id"], ip=client.ip)
        return AuthResult(access, ttl, new_refresh, _user(row, sess["session_id"]))


def authenticate(access_token: str | None) -> User:
    """Resolve the bearer token of a request to the current user (signature + session + account checks)."""
    if not access_token:
        raise AuthenticationError("Authentication required. Please sign in.")
    claims = decode_access_token(access_token)
    now = utcnow()
    with app_conn() as c:
        row = c.execute(
            "SELECT u.*, s.revoked_at, s.expires_at AS session_expires, s.last_used_at FROM auth_sessions s "
            "JOIN users u ON u.user_id = s.user_id WHERE s.session_id = ? AND s.user_id = ?",
            (claims["sid"], int(claims["sub"])),
        ).fetchone()
        if row is None or row["revoked_at"]:
            raise AuthenticationError("Session has been signed out. Please sign in again.", code="SESSION_REVOKED")
        if row["session_expires"] < iso(now):
            raise AuthenticationError("Session expired. Please sign in again.", code="SESSION_EXPIRED")
        if not row["is_active"]:
            raise AuthenticationError("Account disabled.", code="ACCOUNT_DISABLED")
        if (now - datetime.fromisoformat(row["last_used_at"])).total_seconds() > LAST_USED_WRITE_INTERVAL_S:
            c.execute("UPDATE auth_sessions SET last_used_at = ? WHERE session_id = ?", (iso(now), claims["sid"]))
    return _user(row, claims["sid"])


def session_for_refresh_token(refresh_token: str | None) -> str | None:
    if not refresh_token:
        return None
    with app_conn() as c:
        r = c.execute("SELECT session_id FROM auth_sessions WHERE refresh_token_hash = ?", (token_hash(refresh_token),)).fetchone()
        return r["session_id"] if r else None


def revoke_session(session_id: str, reason: str, *, actor: User | None = None, client: ClientInfo | None = None) -> bool:
    with app_conn() as c:
        sess = c.execute("SELECT user_id, revoked_at FROM auth_sessions WHERE session_id = ?", (session_id,)).fetchone()
        if sess is None or sess["revoked_at"]:
            return False
        c.execute("UPDATE auth_sessions SET revoked_at = ?, revoke_reason = ? WHERE session_id = ?", (iso(utcnow()), reason, session_id))
        audit(c, "LOGOUT" if reason == "logout" else "SESSION_REVOKED", "SUCCESS", user_id=sess["user_id"], session_id=session_id,
              ip=client.ip if client else None, detail={"reason": reason, "by": actor.email if actor else None})
        return True


def revoke_all_sessions(user_id: int, reason: str, *, except_session: str | None = None, actor: User | None = None,
                        client: ClientInfo | None = None) -> int:
    with app_conn() as c:
        cur = c.execute("UPDATE auth_sessions SET revoked_at = ?, revoke_reason = ? WHERE user_id = ? AND revoked_at IS NULL "
                        "AND session_id IS NOT ?", (iso(utcnow()), reason, user_id, except_session))
        if cur.rowcount or actor:
            audit(c, "SESSIONS_REVOKED", "SUCCESS", user_id=user_id, ip=client.ip if client else None,
                  detail={"reason": reason, "count": cur.rowcount, "by": actor.email if actor else None})
        return cur.rowcount


def admin_revoke_sessions(admin: User, user_id: int, client: ClientInfo) -> int:
    """Force sign-out (hardening iteration 8: unknown users are a 404, and the acting admin is audited)."""
    with app_conn() as c:
        if c.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone() is None:
            raise NotFoundError("User not found.")
    return revoke_all_sessions(user_id, "revoked_by_admin", actor=admin, client=client)


def list_sessions(user: User) -> list[dict]:
    now = iso(utcnow())
    with app_conn() as c:
        rows = c.execute("SELECT session_id, created_at, last_used_at, expires_at, user_agent, ip_address, rotation_count "
                         "FROM auth_sessions WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ? ORDER BY last_used_at DESC",
                         (user.user_id, now)).fetchall()
    return [{**dict(r), "current": r["session_id"] == user.session_id} for r in rows]


def revoke_own_session(user: User, session_id: str, client: ClientInfo) -> None:
    with app_conn() as c:
        r = c.execute("SELECT user_id FROM auth_sessions WHERE session_id = ?", (session_id,)).fetchone()
    if r is None or r["user_id"] != user.user_id:
        raise NotFoundError("Session not found.")
    revoke_session(session_id, "revoked_by_user", actor=user, client=client)


def change_password(user: User, current: str, new: str, client: ClientInfo) -> int:
    with app_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id = ?", (user.user_id,)).fetchone()
        # Hardening iteration 5: the current-password check shares the login attempt budget. Before, a stolen
        # access token allowed unlimited guesses of the account password through this endpoint.
        now = utcnow()
        attempt = _reserve_attempt(c, user.user_id, now)
        if attempt is None:
            raise _locked_error(_lock_retry_seconds(c, user.user_id, now))
        if not verify_password(current, row["password_hash"]):
            until = _attempt_failed(c, user.user_id, attempt, now)
            audit(c, "PASSWORD_CHANGE", "FAILURE", user_id=user.user_id, email=user.email, ip=client.ip, detail="wrong current password")
            if until:
                # repeated wrong current passwords from a live session look like a hijacked token: end every session
                c.execute("UPDATE auth_sessions SET revoked_at = ?, revoke_reason = 'password_guessing' WHERE user_id = ? AND revoked_at IS NULL",
                          (iso(now), user.user_id))
                audit(c, "ACCOUNT_LOCKED", "FAILURE", user_id=user.user_id, email=user.email, ip=client.ip,
                      detail={"failed_attempts": attempt, "locked_until": iso(until), "via": "change-password", "sessions_revoked": True})
                c.commit()
                raise _locked_error(get_settings().lockout_minutes * 60)
            c.commit()
            raise AuthenticationError("Current password is incorrect.", code="INVALID_CREDENTIALS",
                                      details={"attempts_remaining": get_settings().max_failed_logins - attempt})
        _attempt_succeeded(c, user.user_id)
        problems = password_problems(new, user.email)
        if verify_password(new, row["password_hash"]):
            problems.append("New password must differ from the current one.")
        if problems:
            raise WeakPasswordError("Password does not meet the policy.", details={"problems": problems})
        c.execute("UPDATE users SET password_hash = ?, password_changed_at = ? WHERE user_id = ?",
                  (hash_password(new), iso(utcnow()), user.user_id))
        audit(c, "PASSWORD_CHANGE", "SUCCESS", user_id=user.user_id, email=user.email, session_id=user.session_id, ip=client.ip)
    # every other device must sign in again with the new password
    return revoke_all_sessions(user.user_id, "password_changed", except_session=user.session_id)


# ---------------------------------------------------------------- administration
def list_users() -> list[dict]:
    now = iso(utcnow())
    with app_conn() as c:
        rows = c.execute(
            "SELECT u.user_id, u.email, u.full_name, u.role, u.is_active, u.created_at, u.last_login_at, u.locked_until, "
            "(SELECT COUNT(*) FROM auth_sessions s WHERE s.user_id = u.user_id AND s.revoked_at IS NULL AND s.expires_at > ?) AS active_sessions "
            "FROM users u ORDER BY u.user_id", (now,)).fetchall()
    return [{**dict(r), "is_active": bool(r["is_active"]), "locked": bool(r["locked_until"] and r["locked_until"] > now)} for r in rows]


def update_user(admin: User, user_id: int, *, role: str | None, is_active: bool | None, unlock: bool, client: ClientInfo) -> dict:
    if user_id == admin.user_id and ((role and role != admin.role.value) or is_active is False):
        raise ConflictError("You cannot change your own role or disable your own account.", code="SELF_MODIFICATION")
    with app_conn() as c:
        row = c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise NotFoundError("User not found.")
        demoting_admin = row["role"] == "ADMIN" and ((role and role != "ADMIN") or is_active is False)
        if demoting_admin:
            admins = c.execute("SELECT COUNT(*) FROM users WHERE role = 'ADMIN' AND is_active = 1").fetchone()[0]
            if admins <= 1:
                raise ConflictError("At least one active administrator must remain.", code="LAST_ADMIN")
        changes: dict = {}
        if role and role != row["role"]:
            c.execute("UPDATE users SET role = ? WHERE user_id = ?", (Role(role).value, user_id))
            changes["role"] = {"from": row["role"], "to": role}
        if is_active is not None and bool(row["is_active"]) != is_active:
            c.execute("UPDATE users SET is_active = ? WHERE user_id = ?", (int(is_active), user_id))
            changes["is_active"] = {"from": bool(row["is_active"]), "to": is_active}
        if unlock and row["locked_until"]:
            c.execute("UPDATE users SET locked_until = NULL, failed_logins = 0 WHERE user_id = ?", (user_id,))
            changes["unlocked"] = True
        if changes:
            audit(c, "USER_UPDATED", "SUCCESS", user_id=user_id, email=row["email"], ip=client.ip,
                  detail={"by": admin.email, **changes})
    if changes.get("is_active", {}).get("to") is False:
        revoke_all_sessions(user_id, "account_disabled", actor=admin, client=client)
    return {"user_id": user_id, "changes": changes}


def list_audit(limit: int = 100, event_type: str | None = None) -> list[dict]:
    with app_conn() as c:
        sql = ("SELECT a.event_id, a.occurred_at, a.event_type, a.outcome, a.user_id, COALESCE(a.email, u.email) AS email, "
               "a.session_id, a.ip_address, a.detail FROM auth_audit_log a LEFT JOIN users u ON u.user_id = a.user_id")
        params: list = []
        if event_type:
            sql += " WHERE a.event_type = ?"
            params.append(event_type)
        rows = c.execute(sql + " ORDER BY a.event_id DESC LIMIT ?", (*params, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["detail"] = json.loads(d["detail"]) if d["detail"] and d["detail"].startswith("{") else d["detail"]
        except ValueError:
            pass
        out.append(d)
    return out
