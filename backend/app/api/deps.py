from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Callable

from fastapi import Depends, Header, Request

from ..config import get_settings
from ..core.errors import AuthorizationError
from ..core.security import ROLE_PERMISSIONS, User
from ..schemas.api import UserOut
from ..services import auth

REFRESH_COOKIE = "payinsight_refresh"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "PayInsight"


def bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


@lru_cache(maxsize=8)
def _trusted_networks(spec: str) -> tuple[ipaddress._BaseNetwork, ...]:
    return tuple(ipaddress.ip_network(x.strip(), strict=False) for x in spec.split(",") if x.strip())


def _is_trusted(host: str, networks) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in n for n in networks)


def resolve_client_ip(peer: str | None, forwarded_for: str | None, trusted_spec: str) -> str:
    """Client IP for rate limiting / audit (hardening iteration 7).

    Behind a reverse proxy every request arrives from the proxy's address, so all users shared one
    rate-limit bucket (and the audit log recorded the proxy). X-Forwarded-For is honoured only when the
    direct peer is a configured trusted proxy, walking the chain right-to-left past trusted hops, so a
    client cannot spoof its address by sending the header itself."""
    peer = peer or "unknown"
    networks = _trusted_networks(trusted_spec)
    if not forwarded_for or not _is_trusted(peer, networks):
        return peer
    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_trusted(hop, networks):
            return hop[:64]
    return hops[0][:64] if hops else peer


def client_info(request: Request) -> auth.ClientInfo:
    ip = resolve_client_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"),
                           get_settings().trusted_proxies)
    return auth.ClientInfo(ip=ip, user_agent=request.headers.get("user-agent", "")[:250])


def current_user(authorization: str | None = Header(default=None)) -> User:
    return auth.authenticate(bearer_token(authorization))


def optional_user(authorization: str | None = Header(default=None)) -> User | None:
    token = bearer_token(authorization)
    if not token:
        return None
    try:
        return auth.authenticate(token)
    except Exception:  # expired/revoked tokens are fine for logout
        return None


def require(permission: str) -> Callable[..., User]:
    """Route dependency: authenticated user holding ``permission`` (403 otherwise)."""
    def _dep(user: User = Depends(current_user)) -> User:
        user.require(permission)
        return user
    return _dep


def csrf_guard(request: Request) -> None:
    """Endpoints authenticated by the refresh *cookie* require a custom header. Browsers cannot attach
    custom headers cross-origin without a CORS preflight, which our CORS policy refuses for foreign origins.
    Together with SameSite=Strict this blocks cross-site request forgery against refresh/logout."""
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise AuthorizationError("Missing anti-CSRF header.", code="CSRF_CHECK_FAILED",
                                 details={"required_header": f"{CSRF_HEADER}: {CSRF_VALUE}"})


def user_out(u: User) -> UserOut:
    return UserOut(user_id=u.user_id, email=u.email, full_name=u.full_name, role=u.role.value,
                   permissions=sorted(ROLE_PERMISSIONS[u.role]), allowed_dimensions=sorted(u.allowed_dimensions),
                   session_id=u.session_id)
