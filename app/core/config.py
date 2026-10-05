"""
Central application configuration.

All environment-driven settings live here so the rest of the codebase
never touches `os.environ` directly. Values map 1:1 onto `.env.example`.
"""
from functools import lru_cache
from pathlib import PurePosixPath, PureWindowsPath
import uuid

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "NOVA-GeoRisk Intelligence Suite - FIRRIS Engine"
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
        if (
            self.celery_task_soft_time_limit_seconds <= 0
            or self.celery_task_time_limit_seconds <= self.celery_task_soft_time_limit_seconds
            or self.celery_worker_max_tasks_per_child <= 0
            or self.celery_worker_max_memory_per_child_kb <= 0
        ):
            raise ValueError("Celery task and worker resource limits must be positive and ordered.")
        if min(self.firris_max_pending_tasks_per_organization, self.firris_max_request_bytes,
               self.firris_max_prepared_cells, self.firris_max_feature_layers) <= 0:
            raise ValueError("FIRRIS admission/input capacity limits must be positive")
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
