"""Authentication, session management and RBAC administration tests.

Every "browser" is a separate TestClient with its own cookie jar, so refresh-cookie behaviour is
exercised exactly as a browser would. Demo accounts are never locked or logged out here; tests
that mutate account state use freshly signed-up users.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.core import security
from app.core.errors import RateLimitError
from app.main import app
from app.services import auth

CSRF = {"X-Requested-With": "PayInsight"}
STRONG = "Str0ng!Passw0rd"
COOKIE = "payinsight_refresh"


def browser() -> TestClient:
    return TestClient(app)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def signup(c: TestClient, email: str | None = None, password: str = STRONG, name: str = "Test User"):
    email = email or f"user_{uuid.uuid4().hex[:10]}@example.com"
    r = c.post("/api/auth/signup", json={"email": email, "full_name": name, "password": password})
    return email, r


def login(c: TestClient, email: str, password: str = STRONG):
    return c.post("/api/auth/login", json={"email": email, "password": password})


def code(r) -> str:
    return r.json()["error"]["code"]


@pytest.fixture(autouse=True)
def _app_started(client):
    """Ensure the app lifespan (DB init, demo users) has run via the session-wide client."""
    yield


# ---------------------------------------------------------------- primitives
def test_password_hashing_and_production_cost():
    assert Settings.model_fields["password_hash_iterations"].default == 600_000
    h = security.hash_password("Correct-Horse-9", iterations=1000)
    algo, iters, salt, digest = h.split("$")
    assert algo == "pbkdf2_sha256" and iters == "1000" and len(salt) == 32 and len(digest) == 64
    assert security.verify_password("Correct-Horse-9", h)
    assert not security.verify_password("correct-horse-9", h)
    assert security.hash_password("x", iterations=1000) != security.hash_password("x", iterations=1000)  # salted
    assert security.needs_rehash(h)  # 1000 != configured cost
    assert not security.verify_password("x", "garbage")


def test_password_policy():
    assert security.password_problems(STRONG, "a@b.com") == []
    assert any("10 characters" in p for p in security.password_problems("Ab1!", ""))
    assert any("3 of" in p for p in security.password_problems("alllowercaseletters", ""))
    assert any("common" in p for p in security.password_problems("passw0rd", ""))
    assert any("email" in p for p in security.password_problems("Rahul@2026xyz", "rahul@example.com"))


def test_rate_limiter_unit():
    rl = auth.RateLimiter()
    for _ in range(3):
        rl.check("login", "1.2.3.4", limit=3)
    rl.check("login", "5.6.7.8", limit=3)  # independent key
    with pytest.raises(RateLimitError) as exc:
        rl.check("login", "1.2.3.4", limit=3)
    assert exc.value.status_code == 429 and int(exc.value.headers["Retry-After"]) >= 1


def test_rate_limit_enforced_over_http(monkeypatch):
    monkeypatch.setattr(get_settings(), "auth_rate_limit_per_minute", 3)
    auth.limiter.reset()
    c = browser()
    statuses = [login(c, "nobody@example.com", "x").status_code for _ in range(4)]
    auth.limiter.reset()
    assert statuses == [401, 401, 401, 429]


def test_app_db_migration_from_legacy_schema(tmp_path):
    from app.database.app_store import APP_DDL, _apply_migrations
    db = tmp_path / "legacy.db"
    c = sqlite3.connect(db)
    c.executescript("""CREATE TABLE users (user_id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL, role TEXT NOT NULL, password_hash TEXT NOT NULL);
        CREATE TABLE sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER, expires_at TEXT);
        INSERT INTO users(email, full_name, role, password_hash) VALUES ('old@x.com','Old','VIEWER','h');""")
    c.executescript(APP_DDL)
    _apply_migrations(c)
    _apply_migrations(c)  # idempotent
    cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"is_active", "created_at", "failed_logins", "locked_until", "last_login_at"} <= cols
    assert "sessions" not in tables and {"auth_sessions", "auth_audit_log"} <= tables
    from app.database.app_store import MIGRATIONS
    assert c.execute("PRAGMA user_version").fetchone()[0] == MIGRATIONS[-1][0]  # migrated to the latest version
    assert c.execute("SELECT is_active, created_at IS NOT NULL FROM users").fetchone() == (1, 1)
    c.close()


# ---------------------------------------------------------------- signup
def test_signup_creates_least_privileged_user_with_httponly_refresh_cookie():
    c = browser()
    email, r = signup(c, name="  Priya   Sharma ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["role"] == "VIEWER" and body["user"]["full_name"] == "Priya Sharma"
    assert body["token_type"] == "bearer" and body["expires_in"] == 15 * 60
    assert set(body) == {"access_token", "token_type", "expires_in", "user"}  # refresh token never in JSON
    set_cookie = r.headers["set-cookie"].lower()
    assert COOKIE in set_cookie and "httponly" in set_cookie and "samesite=strict" in set_cookie and "path=/api/auth" in set_cookie
    assert r.headers["cache-control"] == "no-store"
    me = c.get("/api/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == email
    # password and refresh token are stored only as hashes
    with sqlite3.connect(get_settings().app_db_path) as db:
        stored = db.execute("SELECT password_hash FROM users WHERE email = ?", (email,)).fetchone()[0]
        rt_hash = db.execute("SELECT refresh_token_hash FROM auth_sessions WHERE session_id = ?",
                             (body["user"]["session_id"],)).fetchone()[0]
    assert STRONG not in stored and stored.startswith("pbkdf2_sha256$")
    assert rt_hash == hashlib.sha256(c.cookies.get(COOKIE).encode()).hexdigest()


def test_signup_validation():
    c = browser()
    email, r = signup(c)
    assert r.status_code == 201
    _, dup = signup(browser(), email=email.upper())
    assert dup.status_code == 409 and code(dup) == "EMAIL_TAKEN"
    _, weak = signup(browser(), password="short")
    assert weak.status_code == 422 and code(weak) == "WEAK_PASSWORD" and weak.json()["error"]["details"]["problems"]
    _, bad = signup(browser(), email="not-an-email")
    assert bad.status_code == 422 and code(bad) == "INVALID_EMAIL"


def test_signup_can_be_disabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "allow_signup", False)
    _, r = signup(browser())
    assert r.status_code == 403 and code(r) == "SIGNUP_DISABLED"


# ---------------------------------------------------------------- JWT
def test_access_token_claims():
    c = browser()
    _, r = signup(c)
    tok = r.json()["access_token"]
    assert jwt.get_unverified_header(tok)["alg"] == "HS256"
    claims = jwt.decode(tok, options={"verify_signature": False})
    assert claims["iss"] == "payinsight-ai" and claims["aud"] == "payinsight-api" and claims["typ"] == "access"
    assert claims["sid"] == r.json()["user"]["session_id"] and claims["sub"] == str(r.json()["user"]["user_id"])
    assert claims["exp"] - claims["iat"] == 15 * 60 and claims["jti"]


def test_forged_and_expired_tokens_rejected():
    c = browser()
    _, r = signup(c)
    tok = r.json()["access_token"]
    claims = jwt.decode(tok, options={"verify_signature": False})
    secret = security.jwt_secret()
    now = int(time.time())
    cases = {
        "tampered": tok[:-4] + ("AAAA" if not tok.endswith("AAAA") else "BBBB"),
        "alg_none": jwt.encode({**claims, "role": "ADMIN"}, key=None, algorithm="none"),
        "wrong_secret": jwt.encode({**claims, "role": "ADMIN"}, "x" * 64, algorithm="HS256"),
        "wrong_audience": jwt.encode({**claims, "aud": "someone-else"}, secret, algorithm="HS256"),
        "refresh_typ": jwt.encode({**claims, "typ": "refresh"}, secret, algorithm="HS256"),
        "unknown_session": jwt.encode({**claims, "sid": uuid.uuid4().hex}, secret, algorithm="HS256"),
        "garbage": "not.a.jwt",
    }
    for name, forged in cases.items():
        res = c.get("/api/auth/me", headers=bearer(forged))
        assert res.status_code == 401, name
        assert code(res) in {"TOKEN_INVALID", "SESSION_REVOKED"}, (name, code(res))
    expired = jwt.encode({**claims, "iat": now - 3600, "nbf": now - 3600, "exp": now - 1800}, secret, algorithm="HS256")
    res = c.get("/api/auth/me", headers=bearer(expired))
    assert res.status_code == 401 and code(res) == "TOKEN_EXPIRED"
    # role claim is not trusted: a validly signed token claiming ADMIN for a viewer session still acts as VIEWER
    escalated = jwt.encode({**claims, "role": "ADMIN"}, secret, algorithm="HS256")
    assert c.get("/api/admin/users", headers=bearer(escalated)).status_code == 403


# ---------------------------------------------------------------- refresh rotation
def test_refresh_rotates_and_reuse_revokes_session(monkeypatch):
    c = browser()
    _, r = signup(c)
    first_cookie = c.cookies.get(COOKIE)
    r2 = c.post("/api/auth/refresh", headers=CSRF)
    assert r2.status_code == 200, r2.text
    new_access = r2.json()["access_token"]
    assert c.cookies.get(COOKIE) != first_cookie
    assert c.get("/api/auth/me", headers=bearer(new_access)).status_code == 200

    # within the grace window a replay is treated as a benign multi-tab race (session survives)
    thief = browser()
    thief.cookies.set(COOKIE, first_cookie)
    early = thief.post("/api/auth/refresh", headers=CSRF)
    assert early.status_code == 401 and code(early) == "REFRESH_SUPERSEDED"
    assert "set-cookie" not in early.headers  # benign race: cookie kept
    assert c.get("/api/auth/me", headers=bearer(new_access)).status_code == 200

    # after the grace window, replaying a rotated token = theft -> whole session revoked
    monkeypatch.setattr(auth, "REUSE_GRACE_SECONDS", -1)
    thief = browser()
    thief.cookies.set(COOKIE, first_cookie)
    replay = thief.post("/api/auth/refresh", headers=CSRF)
    assert replay.status_code == 401 and code(replay) == "REFRESH_TOKEN_REUSED"
    gone = c.get("/api/auth/me", headers=bearer(new_access))
    assert gone.status_code == 401 and code(gone) == "SESSION_REVOKED"
    assert c.post("/api/auth/refresh", headers=CSRF).status_code == 401  # legitimate holder must sign in again


def test_refresh_requires_csrf_header_and_cookie():
    c = browser()
    signup(c)
    r = c.post("/api/auth/refresh")
    assert r.status_code == 403 and code(r) == "CSRF_CHECK_FAILED"
    r = browser().post("/api/auth/refresh", headers=CSRF)
    assert r.status_code == 401 and code(r) == "REFRESH_MISSING"
    thief = browser()
    thief.cookies.set(COOKIE, "made-up-token")
    r = thief.post("/api/auth/refresh", headers=CSRF)
    assert r.status_code == 401 and code(r) == "REFRESH_INVALID"
    assert 'payinsight_refresh=""' in r.headers.get("set-cookie", "") and "max-age=0" in r.headers["set-cookie"].lower()  # dead cookie cleared


# ---------------------------------------------------------------- logout & sessions
def test_logout_revokes_access_and_refresh():
    c = browser()
    _, r = signup(c)
    tok, cookie = r.json()["access_token"], c.cookies.get(COOKIE)
    out = c.post("/api/auth/logout", headers={**CSRF, **bearer(tok)})
    assert out.status_code == 200 and out.json()["session_revoked"] is True
    assert code(c.get("/api/auth/me", headers=bearer(tok))) == "SESSION_REVOKED"
    replay = browser()
    replay.cookies.set(COOKIE, cookie)
    assert code(replay.post("/api/auth/refresh", headers=CSRF)) == "SESSION_REVOKED"


def test_logout_with_only_refresh_cookie():
    c = browser()
    signup(c)
    sid_cookie = c.cookies.get(COOKIE)
    out = c.post("/api/auth/logout", headers=CSRF)  # access token lost/expired
    assert out.status_code == 200 and out.json()["session_revoked"] is True
    replay = browser()
    replay.cookies.set(COOKIE, sid_cookie)
    assert replay.post("/api/auth/refresh", headers=CSRF).status_code == 401


def test_multi_device_sessions_list_and_revoke():
    laptop, phone = browser(), browser()
    email, r = signup(laptop)
    t_laptop = r.json()["access_token"]
    t_phone = login(phone, email).json()["access_token"]
    sessions = laptop.get("/api/auth/sessions", headers=bearer(t_laptop)).json()
    assert len(sessions) == 2 and sum(s["current"] for s in sessions) == 1
    other = next(s for s in sessions if not s["current"])
    assert laptop.delete(f"/api/auth/sessions/{other['session_id']}", headers=bearer(t_laptop)).status_code == 200
    assert phone.get("/api/auth/me", headers=bearer(t_phone)).status_code == 401
    assert laptop.get("/api/auth/me", headers=bearer(t_laptop)).status_code == 200
    # cannot revoke someone else's session
    _, r2 = signup(browser())
    foreign = r2.json()["user"]["session_id"]
    assert laptop.delete(f"/api/auth/sessions/{foreign}", headers=bearer(t_laptop)).status_code == 404


def test_logout_everywhere():
    a, b = browser(), browser()
    email, r = signup(a)
    tb = login(b, email).json()["access_token"]
    res = a.post("/api/auth/logout-all", headers=bearer(r.json()["access_token"]))
    assert res.json()["sessions_revoked"] == 2
    assert b.get("/api/auth/me", headers=bearer(tb)).status_code == 401


# ---------------------------------------------------------------- brute force
def test_account_lockout_and_admin_unlock(admin):
    c = browser()
    email, r = signup(c)
    uid = r.json()["user"]["user_id"]
    remaining = []
    for _ in range(4):
        res = login(c, email, "Wrong-Passw0rd")
        assert res.status_code == 401 and code(res) == "INVALID_CREDENTIALS"
        remaining.append(res.json()["error"]["details"]["attempts_remaining"])
    assert remaining == [4, 3, 2, 1]
    fifth = login(c, email, "Wrong-Passw0rd")
    assert fifth.status_code == 429 and code(fifth) == "ACCOUNT_LOCKED" and "retry-after" in fifth.headers
    locked = login(c, email)  # correct password is refused while locked
    assert locked.status_code == 429 and code(locked) == "ACCOUNT_LOCKED"
    users = {u["user_id"]: u for u in c.get("/api/admin/users", headers=admin).json()}
    assert users[uid]["locked"] is True
    assert c.patch(f"/api/admin/users/{uid}", json={"unlock": True}, headers=admin).status_code == 200
    assert login(c, email).status_code == 200


def test_unknown_email_indistinguishable_from_wrong_password():
    c = browser()
    email, _ = signup(c)
    a = login(c, "ghost_" + email, STRONG).json()["error"]
    b = login(c, email, "Wrong-Passw0rd").json()["error"]
    assert a["code"] == b["code"] == "INVALID_CREDENTIALS" and a["message"] == b["message"]


# ---------------------------------------------------------------- RBAC administration
def test_admin_endpoints_require_admin(analyst, viewer, admin, client):
    for hdr in (analyst, viewer):
        assert client.get("/api/admin/users", headers=hdr).status_code == 403
        assert client.get("/api/admin/audit", headers=hdr).status_code == 403
        assert client.patch("/api/admin/users/1", json={"role": "VIEWER"}, headers=hdr).status_code == 403
    assert client.get("/api/admin/users").status_code == 401
    users = client.get("/api/admin/users", headers=admin).json()
    assert {"admin@payinsight.demo", "analyst@payinsight.demo", "viewer@payinsight.demo"} <= {u["email"] for u in users}


def test_role_change_takes_effect_immediately_without_new_login(admin):
    c = browser()
    _, r = signup(c)
    uid, tok = r.json()["user"]["user_id"], r.json()["access_token"]
    q = {"question": "Compare payment success rates by bank"}
    denied = c.post("/api/analytics/analyze", json=q, headers=bearer(tok))
    assert denied.status_code == 403 and code(denied) == "ROLE_RESTRICTED_DIMENSION"
    assert c.patch(f"/api/admin/users/{uid}", json={"role": "ANALYST"}, headers=admin).json()["changes"]["role"]["to"] == "ANALYST"
    allowed = c.post("/api/analytics/analyze", json=q, headers=bearer(tok))  # same JWT, role read from DB
    assert allowed.status_code == 200 and allowed.json()["status"] == "completed"
    assert c.get("/api/auth/me", headers=bearer(tok)).json()["role"] == "ANALYST"


def test_deactivation_kills_sessions_and_blocks_login(admin):
    c = browser()
    email, r = signup(c)
    uid, tok = r.json()["user"]["user_id"], r.json()["access_token"]
    assert c.patch(f"/api/admin/users/{uid}", json={"is_active": False}, headers=admin).status_code == 200
    assert c.get("/api/auth/me", headers=bearer(tok)).status_code == 401
    res = login(browser(), email)
    assert res.status_code == 403 and code(res) == "ACCOUNT_DISABLED"
    c.patch(f"/api/admin/users/{uid}", json={"is_active": True}, headers=admin)
    assert login(browser(), email).status_code == 200


def test_admin_cannot_lock_themselves_out(admin, client):
    me = client.get("/api/auth/me", headers=admin).json()
    for body in ({"role": "VIEWER"}, {"is_active": False}):
        res = client.patch(f"/api/admin/users/{me['user_id']}", json=body, headers=admin)
        assert res.status_code == 409 and code(res) == "SELF_MODIFICATION"
    assert client.patch("/api/admin/users/999999", json={"role": "VIEWER"}, headers=admin).status_code == 404


# ---------------------------------------------------------------- password change
def test_change_password_revokes_other_sessions():
    a, b = browser(), browser()
    email, r = signup(a)
    ta = r.json()["access_token"]
    tb = login(b, email).json()["access_token"]
    bad = a.post("/api/auth/change-password", json={"current_password": "nope", "new_password": "N3w!Password"}, headers=bearer(ta))
    assert bad.status_code == 401
    weak = a.post("/api/auth/change-password", json={"current_password": STRONG, "new_password": "weak"}, headers=bearer(ta))
    assert weak.status_code == 422 and code(weak) == "WEAK_PASSWORD"
    same = a.post("/api/auth/change-password", json={"current_password": STRONG, "new_password": STRONG}, headers=bearer(ta))
    assert same.status_code == 422
    ok = a.post("/api/auth/change-password", json={"current_password": STRONG, "new_password": "N3w!Password"}, headers=bearer(ta))
    assert ok.status_code == 200 and ok.json()["other_sessions_revoked"] == 1
    assert a.get("/api/auth/me", headers=bearer(ta)).status_code == 200  # current device stays signed in
    assert b.get("/api/auth/me", headers=bearer(tb)).status_code == 401
    assert login(browser(), email).status_code == 401
    assert login(browser(), email, "N3w!Password").status_code == 200


# ---------------------------------------------------------------- audit & headers
def test_audit_log_records_security_events(admin, client):
    c = browser()
    email, _ = signup(c)
    login(c, email, "Wrong-Passw0rd")
    events = client.get("/api/admin/audit?limit=500", headers=admin).json()
    mine = [(e["event_type"], e["outcome"]) for e in events if e["email"] == email]
    assert all(e["email"] for e in events if e["user_id"])  # user-linked events resolve to an email
    assert ("SIGNUP", "SUCCESS") in mine and ("LOGIN", "FAILURE") in mine
    types = {e["event_type"] for e in events}
    assert {"SIGNUP", "LOGIN", "TOKEN_REFRESH", "LOGOUT", "REFRESH_TOKEN_REUSE", "ACCOUNT_LOCKED", "USER_UPDATED"} <= types
    only = client.get("/api/admin/audit?event_type=SIGNUP", headers=admin).json()
    assert only and all(e["event_type"] == "SIGNUP" for e in only)
    # no secrets in the audit trail
    blob = str(events)
    assert STRONG not in blob and "Wrong-Passw0rd" not in blob


def test_security_headers(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
