"""
Central application configuration.

All environment-driven settings live here so the rest of the codebase
never touches `os.environ` directly. Values map 1:1 onto `.env.example`.
"""
from functools import lru_cache
from pathlib import PurePosixPath, PureWindowsPath
import uuid
from datetime import date

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "NOVA-GeoRisk Intelligence Suite - FRRIS Engine"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    debug: bool = True

    # --- Security ---
    internal_api_secret: str = "changeme"
    expose_api_docs: bool = False
    public_outputs_enabled: bool = False
    cors_allowed_origins: str = ""

    # --- Browser-facing BFF ---
    internal_api_base_url: str = "http://api:8000"
    session_cookie_name: str = "nova_session"
    session_cookie_secure: bool = True
    session_ttl_seconds: int = 28800
    session_redis_prefix: str = "nova:bff:session:"

    # Provider-neutral OIDC configuration.  Login remains disabled until
    # an owner selects and configures a standards-compliant provider.
    oidc_issuer_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_scopes: str = "openid profile email"
    oidc_allowed_algorithms: str = "RS256,ES256"
    oidc_token_endpoint_auth_method: str = "client_secret_post"
    oidc_state_cookie_name: str = "nova_oidc_state"
    oidc_state_redis_prefix: str = "nova:bff:oidc-state:"
    oidc_state_ttl_seconds: int = 600
    membership_provisioning_policy: str = "strict"
    oidc_bootstrap_first_user_enabled: bool = False
    oidc_bootstrap_organization_id: uuid.UUID = uuid.UUID(
        "00000000-0000-0000-0000-000000000001"
    )

    # --- Database ---
    database_url: str = "postgresql+psycopg2://nova_user:nova_password@localhost:5432/nova_georisk"
    db_echo: bool = False

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_task_soft_time_limit_seconds: int = 10800
    celery_task_time_limit_seconds: int = 14400
    celery_worker_max_tasks_per_child: int = 1
    celery_worker_max_memory_per_child_kb: int = 3145728

    # --- FIRRIS bounded queue/input policy ---
    firris_max_pending_tasks_per_organization: int = 32
    firris_max_request_bytes: int = 16777216
    firris_max_prepared_cells: int = 1000000
    firris_max_feature_layers: int = 32
    # Submission preflight (plan 4.1): metadata-only provider checks, per-minute limits and a hard timeout.
    firris_preflight_per_user_per_minute: int = 10
    firris_preflight_per_organization_per_minute: int = 30
    firris_preflight_timeout_seconds: float = 20.0
    # Area playground capacity check (P6): pure geometry, called while the user edits, so higher limits.
    aoi_capacity_per_user_per_minute: int = 60
    aoi_capacity_per_organization_per_minute: int = 300

    # --- Google Earth Engine ---
    gee_service_account_email: str = ""
    gee_service_account_key_path: str = ""
    gee_project_id: str = ""

    # --- Sampling strategy defaults (Doc 0 §14 / §6 JSON schema) ---
    default_sample_size: int = 5000
    min_samples: int = 1000
    max_samples: int = 5000
    train_split: float = 0.70
    min_samples_per_class: int = 30
    random_seed: int = 12345

    # --- Cloud masking thresholds (Doc 0 §9) ---
    cloud_threshold_land_cover: float = 0.10
    cloud_threshold_flood_sar: float = 0.20

    # --- Output storage ---
    artifact_storage_backend: str = "filesystem"
    output_storage_dir: str = "outputs"

    # --- Subscriptions and credits (docs/PLATFORM_SUBSCRIPTIONS_PLAN.md) ---
    # Off until release Phase B: every organisation needs a subscription before this is switched on,
    # otherwise every submission returns 402. Read and download routes are never affected.
    billing_enforcement_enabled: bool = False
    billing_timezone: str = "Africa/Dar_es_Salaam"
    # Q4 (decided 2026-11-21): unused monthly credits expire at month end (no rollover); top-up credits do not.
    billing_monthly_credits_roll_over: bool = False
    billing_top_up_credits_expire: bool = False
    # Q5 (decided 2026-11-21): warn at 90% and at 100%; at 100% block new analyses until space is freed or
    # added. Viewing and downloads are never blocked.
    billing_storage_block_at_limit: bool = True
    billing_storage_warning_percents: list[int] = [90]
    # Q7 (decided 2026-11-21): an Expired or Cancelled organisation keeps viewing and downloads for 2 days.
    billing_view_grace_days: int | None = 2

    # --- Seller identity on payment receipts and My subscription (Q6, decided 2026-11-21) ---
    # Configuration only, so a change of seller (for example to NOVAREX Ltd) needs no code change.
    # Receipts are refused (503 receipts_not_configured) until the legal name is set.
    seller_legal_name: str = ""
    seller_tin: str = ""
    seller_address: str = ""
    # A PNG or JPEG file on the server, read when a receipt is drawn; unset = no logo.
    seller_logo_path: str | None = None
    # none | inclusive | exclusive. "inclusive": the amount paid includes VAT; "exclusive": VAT is added on
    # top of the plan or top-up price. Receipts show the VAT line in every mode.
    seller_vat_mode: str = "none"
    seller_vat_rate_percent: int = 18

    # --- Sessions, devices and login history (plan section 6) ---
    # Local city-level GeoIP file (.mmdb, for example DB-IP Lite); unset = no locations. Never an online service.
    geoip_database_path: str | None = None
    # Full IP addresses are kept this long for security, then removed; city and country stay.
    session_ip_retention_days: int = 30
    # Q9: how long login history is kept; None = until the client decides.
    session_history_retention_days: int | None = None
    # Proxies whose X-Forwarded-For entries are trusted (the nginx containers on the Docker network).
    session_trusted_proxy_cidrs: list[str] = ["127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12",
                                              "192.168.0.0/16", "fc00::/7"]
    # "Last active" on the device list is updated at most this often per session.
    session_last_seen_interval_seconds: int = 300

    # --- NOVA ARI console (plan section 8) ---
    # "Payment overdue": an active, sold subscription whose recorded plan payments end more than this many
    # days ago (or that started this long ago with no plan payment).
    billing_payment_overdue_grace_days: int = 7
    # Go-live grace: periods are only judged from this date (set in the turn-on checklist), so customers
    # backfilled without payment records are not all flagged at once. None = no go-live grace.
    billing_overdue_grace_from: date | None = None
    billing_expiring_soon_days: int = 7
    # API-request and download counters (Redis buffer, flushed to Postgres). Tests switch this off.
    usage_counting_enabled: bool = True

    # --- Abliner Mobile Money (docs/ABLINER_PAYMENTS_PLAN.md) ---
    # Off by default: no new payments. Payments already started still settle (webhook, reconciliation).
    abliner_payments_enabled: bool = False
    abliner_api_base_url: str = "https://abliner.net"
    # Set only on the server (ABLINER_API_KEY, ABLINER_WEBHOOK_SECRET). SecretStr keeps them out of repr and logs.
    abliner_api_key: SecretStr = SecretStr("")
    abliner_webhook_secret: SecretStr = SecretStr("")
    abliner_callback_url: str = "https://app.novageorisk.com/api/v1/webhooks/abliner"
    abliner_reconcile_min_age_minutes: int = 3
    # A payment with no result from Abliner after this long is "expired" (no credits).
    abliner_intent_expiry_minutes: int = 30

    @property
    def allowed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def oidc_is_configured(self) -> bool:
        return all(
            [
                self.oidc_issuer_url,
                self.oidc_client_id,
                self.oidc_client_secret,
                self.oidc_redirect_uri,
            ]
        )

    @property
    def oidc_scope_list(self) -> list[str]:
        return [scope for scope in self.oidc_scopes.split() if scope]

    @property
    def oidc_algorithm_list(self) -> list[str]:
        return [algorithm.strip() for algorithm in self.oidc_allowed_algorithms.split(",") if algorithm.strip()]

    @model_validator(mode="after")
    def _production_security_invariants(self) -> "Settings":
        environment = self.app_env.strip().lower()
        if self.seller_vat_mode not in {"none", "inclusive", "exclusive"} or not 0 <= self.seller_vat_rate_percent <= 100:
            raise ValueError("SELLER_VAT_MODE is none, inclusive or exclusive; SELLER_VAT_RATE_PERCENT is 0-100.")
        if any(not 1 <= value <= 99 for value in self.billing_storage_warning_percents):
            raise ValueError("BILLING_STORAGE_WARNING_PERCENTS are between 1 and 99 (100% is always a warning).")
        if (
            self.celery_task_soft_time_limit_seconds <= 0
            or self.celery_task_time_limit_seconds <= self.celery_task_soft_time_limit_seconds
            or self.celery_worker_max_tasks_per_child <= 0
            or self.celery_worker_max_memory_per_child_kb <= 0
        ):
            raise ValueError("Celery task and worker resource limits must be positive and ordered.")
        if min(self.firris_max_pending_tasks_per_organization, self.firris_max_request_bytes,
               self.firris_max_prepared_cells, self.firris_max_feature_layers) <= 0:
            raise ValueError("FRRIS admission/input capacity limits must be positive")
        if self.artifact_storage_backend.strip().lower() != "filesystem":
            raise ValueError("ARTIFACT_STORAGE_BACKEND currently supports only filesystem.")
        if self.membership_provisioning_policy.lower() not in {"strict", "optional_invite"}:
            raise ValueError("MEMBERSHIP_PROVISIONING_POLICY must be strict or optional_invite.")
        if self.oidc_bootstrap_first_user_enabled and environment not in {
            "development",
            "staging",
        }:
            raise ValueError(
                "OIDC first-user bootstrap is allowed only in development or staging."
            )
        if self.oidc_token_endpoint_auth_method not in {"client_secret_post", "client_secret_basic"}:
            raise ValueError(
                "OIDC_TOKEN_ENDPOINT_AUTH_METHOD must be client_secret_post or client_secret_basic."
            )
        if not self.oidc_algorithm_list or any(
            algorithm.lower() == "none" or algorithm.upper().startswith("HS")
            for algorithm in self.oidc_algorithm_list
        ):
            raise ValueError("OIDC_ALLOWED_ALGORITHMS must contain asymmetric signed algorithms.")
        if "openid" not in self.oidc_scope_list:
            raise ValueError("OIDC_SCOPES must include openid.")
        if environment == "production":
            secret = self.internal_api_secret.strip()
            if (
                not secret
                or secret.lower() in {"changeme", "replace-with-a-long-random-secret"}
                or len(secret) < 32
            ):
                raise ValueError("Production requires a non-default INTERNAL_API_SECRET of at least 32 characters.")
            if self.debug:
                raise ValueError("DEBUG must be false in production.")
            if "*" in self.allowed_cors_origins:
                raise ValueError("Wildcard CORS origins are not allowed in production.")
            unsafe_database_markers = {
                "nova_password",
                "replace-with-a-long-random-password",
            }
            if any(marker in self.database_url for marker in unsafe_database_markers):
                raise ValueError("Production DATABASE_URL must not use a development or placeholder password.")
            if not self.session_cookie_secure:
                raise ValueError("Production session cookies must be secure.")
            if self.public_outputs_enabled:
                raise ValueError("Production must use authorized result delivery, not public /outputs.")
            if self.expose_api_docs:
                raise ValueError("Production API docs must remain private.")
            # Validate the deployment path's syntax, not the test runner's OS.
            # Production containers use POSIX paths even when CI runs on Windows.
            storage_path = self.output_storage_dir.strip()
            if not (PurePosixPath(storage_path).is_absolute()
                    or PureWindowsPath(storage_path).is_absolute()):
                raise ValueError("Production OUTPUT_STORAGE_DIR must be an absolute shared path.")
            if not self.oidc_is_configured:
                raise ValueError("Production requires complete OIDC configuration.")
            if not self.oidc_issuer_url.lower().startswith("https://"):
                raise ValueError("Production OIDC issuer must use HTTPS.")
            if not self.oidc_redirect_uri.lower().startswith("https://"):
                raise ValueError("Production OIDC redirect URI must use HTTPS.")
        return self


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import and call this, never instantiate Settings() directly."""
    return Settings()
