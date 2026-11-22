"""Request / response models for the HTTP API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class SignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    full_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: Literal["ADMIN", "ANALYST", "VIEWER"]
    permissions: list[str]
    allowed_dimensions: list[str]
    session_id: str | None = None


class AuthResponse(BaseModel):
    """Access token in the body; the refresh token is set as an httpOnly cookie, never returned in JSON."""
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


class SessionOut(BaseModel):
    session_id: str
    created_at: str
    last_used_at: str
    expires_at: str
    user_agent: str | None
    ip_address: str | None
    rotation_count: int
    current: bool


class AdminUserOut(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: Literal["ADMIN", "ANALYST", "VIEWER"]
    is_active: bool
    locked: bool
    created_at: str | None
    last_login_at: str | None
    active_sessions: int


class UpdateUserRequest(BaseModel):
    role: Literal["ADMIN", "ANALYST", "VIEWER"] | None = None
    is_active: bool | None = None
    unlock: bool = False


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    planner: str
    database: dict[str, Any] | None = None
    cache: dict[str, Any] | None = None
    rate_limiter: dict[str, Any] | None = None


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class AnalysisResponse(Loose):
    id: str
    question: str
    status: Literal["completed", "needs_clarification", "rejected"]
    planner: dict[str, Any]
    summary: str | None = None
    message: str | None = None


class HistoryItem(BaseModel):
    analysis_id: str
    question: str
    status: str
    intent: str | None
    scenario_id: str | None
    created_at: str


class ActivateScenarioRequest(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=2)
    reseed: bool = False


class ScenarioActivation(Loose):
    active: str
    data_profile: str
    regenerated: bool
    cache_cleared: bool


class SQLRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)


class SQLValidationOut(BaseModel):
    valid: bool
    tables: list[str]
    reasons: list[str]
    limit_applied: int | None
    executed_sql: str | None = None
