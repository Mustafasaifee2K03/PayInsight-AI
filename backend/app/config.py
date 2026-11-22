"""Application configuration loaded from environment variables / .env."""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_prefix="PAYINSIGHT_",
        extra="ignore",
    )

    app_name: str = "PayInsight AI"
    data_dir: Path = PROJECT_DIR / "data"
    # Fixed historical window; the application never uses the machine clock for analytics.
    data_start_date: date = date(2025, 9, 1)
    data_days: int = 60
    default_row_count: int = 30_000
    random_seed: int = 20250901

    demo_password: str = "PayInsight@2026"

    # ---- authentication (JWT access tokens + DB-backed refresh sessions)
    # If unset, a random 256-bit secret is generated once and persisted to <data_dir>/.jwt_secret.
    jwt_secret: str | None = None
    jwt_issuer: str = "payinsight-ai"
    jwt_audience: str = "payinsight-api"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 7
    refresh_cookie_secure: bool = False          # set true when served over HTTPS
    password_hash_iterations: int = 600_000     # OWASP 2023 recommendation for PBKDF2-HMAC-SHA256
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    auth_rate_limit_per_minute: int = 30        # per client IP, on login/signup/refresh
    allow_signup: bool = True
    rate_limit_backend: str = "memory"          # pluggable: see app/core/ratelimit.py (register_backend)
    # Proxies whose X-Forwarded-For header is believed (comma-separated IPs/CIDRs). Loopback covers the
    # Vite dev proxy; add your load balancer's range in production. Empty = never trust the header.
    trusted_proxies: str = "127.0.0.1,::1"
    app_db_write_gate: bool = True              # FIFO in-process writer queue for app.db (iteration 10)
    audit_retention_days: int = 365             # auth_audit_log rows older than this are purged
    housekeeping_interval_seconds: int = 600    # purge cadence (per process), instead of on every login

    query_timeout_ms: int = 3_000
    max_result_rows: int = 5_000
    # Process-wide SQLite heap ceiling (PRAGMA hard_heap_limit). A single runaway expression such as
    # printf('%.*c', 1e9, 'x') could otherwise allocate ~1 GB on an 8 GB machine. 0 disables it.
    sqlite_heap_limit_mb: int = 512
    cache_max_entries: int = 256
    cache_ttl_seconds: int = 600

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"

    @property
    def data_end_date(self) -> date:
        from datetime import timedelta

        return self.data_start_date + timedelta(days=self.data_days - 1)

    @property
    def jwt_secret_path(self) -> Path:
        return self.data_dir / ".jwt_secret"

    @property
    def app_db_path(self) -> Path:
        return self.data_dir / "app.db"

    def payments_db_path(self, profile: str) -> Path:
        return self.data_dir / f"payments_{profile}.db"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s
