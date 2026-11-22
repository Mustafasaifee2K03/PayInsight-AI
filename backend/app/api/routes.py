"""HTTP routes. Handlers stay thin: auth + delegation to services."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ..config import get_settings
from ..core.errors import AuthorizationError, NotFoundError
from ..core.security import User
from ..database import app_store
from ..database.manager import get_db
from ..services import analysis, dashboard, data_quality, scenarios
from ..services.planner import ENGINE_NAME
from ..services.query_executor import cache, execute
from ..services.sql_compiler import CompiledQuery
from ..services.sql_validator import validate_sql
from ..schemas.api import (ActivateScenarioRequest, AnalysisResponse, AnalyzeRequest, HealthResponse, HistoryItem,
                           Loose, ScenarioActivation, SQLRequest, SQLValidationOut)
from .deps import current_user, require

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Public liveness/readiness probe. Deliberately minimal (hardening iteration 8): it used to expose the
    database file name, data generation, transaction volume and cache statistics to anonymous callers."""
    ok = get_db().path.exists()
    return HealthResponse(status="ok" if ok else "degraded", app=get_settings().app_name, planner=ENGINE_NAME)


@router.get("/api/system/status", response_model=HealthResponse, tags=["system"])
def system_status(user: User = Depends(require("users:manage"))) -> HealthResponse:
    """Operational detail for administrators: active dataset, row count, cache and rate-limiter state."""
    from ..services.auth import limiter
    db = get_db()
    ok = db.path.exists()
    rows = None
    if ok:
        rows = execute(CompiledQuery("Health check", "SELECT COUNT(*) AS n FROM transactions_canonical"), use_cache=False).rows[0]["n"]
    return HealthResponse(status="ok" if ok else "degraded", app=get_settings().app_name, planner=ENGINE_NAME,
                          database={"profile": db.profile, "path": db.path.name, "canonical_rows": rows, "generation": db.generation},
                          cache=cache.stats(), rate_limiter={"backend": get_settings().rate_limit_backend, "tracked_keys": limiter.backend.size()})


# ---------------------------------------------------------------- dashboard & datasets
@router.get("/api/dashboard/overview", response_model=Loose, tags=["dashboard"])
def dashboard_overview(window_days: int = Query(30, ge=1, le=60), user: User = Depends(current_user)):
    user.require("dashboard")
    return dashboard.overview(user, window_days)


@router.get("/api/datasets", response_model=Loose, tags=["dashboard"])
def datasets(user: User = Depends(current_user)):
    return dashboard.datasets()


# ---------------------------------------------------------------- quality & reconciliation (ADMIN)
@router.get("/api/quality", response_model=Loose, tags=["data-quality"])
def quality(user: User = Depends(current_user)):
    user.require("quality")
    return data_quality.run_quality_checks()


@router.get("/api/reconciliation", response_model=Loose, tags=["data-quality"])
def reconciliation(user: User = Depends(current_user)):
    user.require("reconciliation")
    return data_quality.run_reconciliation()


# ---------------------------------------------------------------- scenarios
@router.get("/api/scenarios", response_model=Loose, tags=["scenarios"])
def list_scenarios(user: User = Depends(current_user)):
    return scenarios.list_scenarios()


@router.post("/api/scenarios/activate", response_model=ScenarioActivation, tags=["scenarios"])
def activate_scenario(body: ActivateScenarioRequest, user: User = Depends(current_user)):
    return scenarios.activate(body.scenario_id, user, reseed=body.reseed)


# ---------------------------------------------------------------- analytics
@router.post("/api/analytics/analyze", response_model=AnalysisResponse, tags=["analytics"])
def analyze(body: AnalyzeRequest, user: User = Depends(current_user)):
    user.require("analytics")
    sid = scenarios.active_scenario_id()
    result = analysis.run_analysis(body.question, user, sid)
    app_store.save_history(result["id"], user.user_id, body.question, result["status"],
                           (result.get("interpretation") or {}).get("intent"), sid, result["created_at"], result)
    return result


@router.get("/api/analytics/history", response_model=list[HistoryItem], tags=["analytics"])
def history(limit: int = Query(30, ge=1, le=200), user: User = Depends(current_user)):
    return app_store.list_history(user.user_id, limit)


@router.get("/api/analytics/result/{analysis_id}", response_model=AnalysisResponse, tags=["analytics"])
def get_result(analysis_id: str, user: User = Depends(current_user)):
    item = app_store.get_history_item(analysis_id)
    if item is None:
        raise NotFoundError("Analysis not found.")
    if item["user_id"] != user.user_id and user.role.value != "ADMIN":
        raise AuthorizationError("You can only view your own analyses.")
    analysis.authorize_stored_result(item["result"], user)
    return item["result"]


# ---------------------------------------------------------------- SQL safety (validate: ANALYST/ADMIN, execute: ADMIN)
@router.post("/api/sql/validate", response_model=SQLValidationOut, tags=["sql"])
def sql_validate(body: SQLRequest, user: User = Depends(current_user)):
    if not (user.can("sql:validate") or user.can("sql:sandbox")):
        raise AuthorizationError(f"Role {user.role.value} cannot use the SQL validator.")
    v = validate_sql(body.sql, max_rows=get_settings().max_result_rows)
    return SQLValidationOut(**v.as_dict(), executed_sql=v.sql if v.valid else None)


@router.post("/api/sql/execute", response_model=Loose, tags=["sql"])
def sql_execute(body: SQLRequest, user: User = Depends(current_user)):
    user.require("sql:sandbox")
    run = execute(CompiledQuery("Admin SQL sandbox", body.sql), use_cache=False, max_rows=500)
    return {**run.meta(), "columns": run.columns, "rows": run.rows}
