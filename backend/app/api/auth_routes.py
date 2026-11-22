"""Authentication, session-management and user-administration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..core.errors import AppError, _envelope
from ..core.security import User
from ..schemas.api import (AdminUserOut, AuthResponse, ChangePasswordRequest, LoginRequest, Loose, SessionOut, SignupRequest,
                           UpdateUserRequest, UserOut)
from ..services import auth
from .deps import REFRESH_COOKIE, client_info, csrf_guard, current_user, optional_user, require, user_out

router = APIRouter()
COOKIE_PATH = "/api/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(REFRESH_COOKIE, token, max_age=s.refresh_token_ttl_days * 86400, path=COOKIE_PATH,
                        httponly=True, secure=s.refresh_cookie_secure, samesite="strict")


def _clear_refresh_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH, httponly=True, secure=s.refresh_cookie_secure, samesite="strict")


def _auth_response(response: Response, result: auth.AuthResult) -> AuthResponse:
    _set_refresh_cookie(response, result.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    return AuthResponse(access_token=result.access_token, expires_in=result.expires_in, user=user_out(result.user))


@router.post("/api/auth/signup", response_model=AuthResponse, status_code=201, tags=["auth"])
def signup(body: SignupRequest, request: Request, response: Response) -> AuthResponse:
    """Self-registration. New accounts get the least-privileged role (VIEWER)."""
    return _auth_response(response, auth.signup(body.email, body.full_name, body.password, client_info(request)))


@router.post("/api/auth/login", response_model=AuthResponse, tags=["auth"])
def login(body: LoginRequest, request: Request, response: Response) -> AuthResponse:
    return _auth_response(response, auth.login(body.email, body.password, client_info(request)))


@router.post("/api/auth/refresh", response_model=AuthResponse, tags=["auth"], dependencies=[Depends(csrf_guard)])
def refresh(request: Request, response: Response, payinsight_refresh: str | None = Cookie(default=None)) -> AuthResponse:
    """Exchange the refresh cookie for a new access token. The refresh token is rotated on every call."""
    try:
        return _auth_response(response, auth.refresh(payinsight_refresh, client_info(request)))
    except AppError as exc:
        # The injected `response` is discarded when an exception propagates, so build the error response
        # here to be able to clear a dead cookie (but keep it on a benign multi-tab race).
        err = JSONResponse(status_code=exc.status_code,
                           content=_envelope(exc.code, exc.message, exc.details),
                           headers=exc.headers)
        if exc.code != "REFRESH_SUPERSEDED":
            _clear_refresh_cookie(err)
        return err


@router.post("/api/auth/logout", tags=["auth"], dependencies=[Depends(csrf_guard)])
def logout(request: Request, response: Response, user: User | None = Depends(optional_user),
           payinsight_refresh: str | None = Cookie(default=None)) -> dict:
    """Revoke the current session (identified by the access token, or by the refresh cookie if the token expired)."""
    sid = user.session_id if user else auth.session_for_refresh_token(payinsight_refresh)
    revoked = auth.revoke_session(sid, "logout", actor=user, client=client_info(request)) if sid else False
    _clear_refresh_cookie(response)
    return {"status": "logged_out", "session_revoked": revoked}


@router.post("/api/auth/logout-all", tags=["auth"])
def logout_all(response: Response, user: User = Depends(current_user)) -> dict:
    count = auth.revoke_all_sessions(user.user_id, "logout_all")
    _clear_refresh_cookie(response)
    return {"status": "logged_out_everywhere", "sessions_revoked": count}


@router.get("/api/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(current_user)) -> UserOut:
    return user_out(user)


@router.get("/api/auth/sessions", response_model=list[SessionOut], tags=["auth"])
def sessions(user: User = Depends(require("account"))) -> list[dict]:
    return auth.list_sessions(user)


@router.delete("/api/auth/sessions/{session_id}", tags=["auth"])
def revoke(session_id: str, request: Request, user: User = Depends(require("account"))) -> dict:
    auth.revoke_own_session(user, session_id, client_info(request))
    return {"status": "revoked", "session_id": session_id}


@router.post("/api/auth/change-password", tags=["auth"])
def change_password(body: ChangePasswordRequest, request: Request, user: User = Depends(require("account"))) -> dict:
    revoked = auth.change_password(user, body.current_password, body.new_password, client_info(request))
    return {"status": "password_changed", "other_sessions_revoked": revoked}


# ---------------------------------------------------------------- administration (ADMIN)
@router.get("/api/admin/users", response_model=list[AdminUserOut], tags=["admin"])
def admin_users(_: User = Depends(require("users:manage"))) -> list[dict]:
    return auth.list_users()


@router.patch("/api/admin/users/{user_id}", response_model=Loose, tags=["admin"])
def admin_update_user(user_id: int, body: UpdateUserRequest, request: Request, admin: User = Depends(require("users:manage"))):
    return auth.update_user(admin, user_id, role=body.role, is_active=body.is_active, unlock=body.unlock, client=client_info(request))


@router.post("/api/admin/users/{user_id}/revoke-sessions", tags=["admin"])
def admin_revoke_sessions(user_id: int, request: Request, admin: User = Depends(require("users:manage"))) -> dict:
    return {"sessions_revoked": auth.admin_revoke_sessions(admin, user_id, client_info(request))}


@router.get("/api/admin/audit", response_model=list[Loose], tags=["admin"])
def admin_audit(limit: int = Query(100, ge=1, le=500), event_type: str | None = Query(None, max_length=40),
                _: User = Depends(require("audit:read"))) -> list[dict]:
    return auth.list_audit(limit, event_type)
