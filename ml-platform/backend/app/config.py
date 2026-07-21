"""Application configuration via pydantic-settings."""

from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit, urlunsplit

from pydantic import Field, PrivateAttr, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


DEFAULT_SECRET_KEY = "change-me-in-production"


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        hide_input_in_errors=True,
    )

    def __init__(self, **values: object) -> None:
        try:
            super().__init__(**values)
        except ValidationError as error:
            line_errors = []
            for detail in error.errors(include_url=False):
                redacted_detail = {
                    "type": detail["type"],
                    "loc": detail["loc"],
                    "input": "[redacted]",
                }
                if "ctx" in detail:
                    redacted_detail["ctx"] = detail["ctx"]
                line_errors.append(redacted_detail)
            raise ValidationError.from_exception_data(
                self.__class__.__name__,
                line_errors,
                hide_input=True,
            ) from None

    app_mode: Literal["local", "production"] = "local"
    database_url: str = Field(
        default="sqlite:///./ml_platform.db", repr=False, exclude=True
    )
    database_pool_size: int = Field(default=5, gt=0)
    database_max_overflow: int = Field(default=10, ge=0)
    database_pool_timeout_seconds: int = Field(default=30, gt=0)

    secret_key: SecretStr = Field(
        default=SecretStr(DEFAULT_SECRET_KEY), exclude=True
    )
    secret_key_file: str | None = Field(default=None, repr=False, exclude=True)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    task_backend: Literal["local", "celery"] = "local"
    celery_broker_url: SecretStr | None = Field(default=None, exclude=True)
    celery_result_backend: SecretStr | None = Field(default=None, exclude=True)
    redis_events_url: SecretStr | None = Field(default=None, exclude=True)
    task_soft_timeout_seconds: int = Field(default=3600, gt=0)
    task_hard_timeout_seconds: int = Field(default=3900, gt=0)

    artifact_storage_backend: Literal["local", "minio"] = "local"
    artifact_storage_dir: str = "./artifact_store"
    minio_endpoint: str | None = Field(default=None, repr=False, exclude=True)
    minio_bucket: str = "ml-platform"
    minio_access_key: SecretStr | None = Field(default=None, exclude=True)
    minio_access_key_file: str | None = Field(
        default=None, repr=False, exclude=True
    )
    minio_secret_key: SecretStr | None = Field(default=None, exclude=True)
    minio_secret_key_file: str | None = Field(
        default=None, repr=False, exclude=True
    )
    minio_secure: bool = False

    mlflow_tracking_uri: str | None = None
    mlflow_backend_store_uri: SecretStr | None = Field(default=None, exclude=True)
    mlflow_artifact_root: str | None = None
    tensorboard_gateway_url: str | None = None
    tensorboard_session_secret: SecretStr | None = Field(default=None, exclude=True)
    tensorboard_session_secret_file: str | None = Field(
        default=None, repr=False, exclude=True
    )
    tensorboard_session_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    tensorboard_idle_timeout_seconds: int = Field(default=600, ge=60, le=86400)
    training_checkpoint_interval_epochs: int = Field(default=5, ge=1, le=1000)
    training_stale_after_seconds: int = Field(default=300, ge=30, le=86400)
    inference_runtime_url: str | None = None
    inference_internal_secret: SecretStr | None = Field(default=None, exclude=True)
    inference_internal_secret_file: str | None = Field(
        default=None, repr=False, exclude=True
    )
    inference_conversion_timeout_seconds: int = Field(default=120, ge=10, le=600)
    inference_load_timeout_seconds: int = Field(default=60, ge=5, le=300)
    inference_predict_timeout_seconds: int = Field(default=30, ge=1, le=120)
    inference_rate_limit_capacity: int = Field(default=100, ge=1, le=100000)
    inference_rate_limit_refill_per_second: float = Field(
        default=10.0, gt=0, le=10000
    )
    inference_log_retention_days: int = Field(default=30, ge=1, le=365)
    inference_rollout_observation_seconds: int = Field(default=60, ge=10, le=3600)

    # LLM / RAG settings
    llm_api_url: str = Field(
        default="https://api.openai.com/v1/chat/completions",
        repr=False,
        exclude=True,
    )
    llm_api_key: str = Field(default="", repr=False, exclude=True)
    llm_model: str = "gpt-3.5-turbo"

    _resolved_secret_key: SecretStr = PrivateAttr()
    _resolved_minio_access_key: SecretStr | None = PrivateAttr(default=None)
    _resolved_minio_secret_key: SecretStr | None = PrivateAttr(default=None)
    _resolved_tensorboard_session_secret: SecretStr | None = PrivateAttr(default=None)
    _resolved_inference_internal_secret: SecretStr | None = PrivateAttr(default=None)

    @property
    def resolved_secret_key(self) -> SecretStr:
        return self._resolved_secret_key

    @property
    def resolved_minio_access_key(self) -> SecretStr | None:
        return self._resolved_minio_access_key

    @property
    def resolved_minio_secret_key(self) -> SecretStr | None:
        return self._resolved_minio_secret_key

    @property
    def resolved_tensorboard_session_secret(self) -> SecretStr | None:
        return self._resolved_tensorboard_session_secret

    @property
    def resolved_inference_internal_secret(self) -> SecretStr | None:
        return self._resolved_inference_internal_secret

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        resolved_secret = self._resolve_secret_pair(
            "secret_key", "secret_key_file", required=True
        )
        self.secret_key = resolved_secret
        self._resolved_secret_key = self.secret_key
        self._resolved_minio_access_key = self._resolve_secret_pair(
            "minio_access_key", "minio_access_key_file"
        )
        self._resolved_minio_secret_key = self._resolve_secret_pair(
            "minio_secret_key", "minio_secret_key_file"
        )
        self._resolved_tensorboard_session_secret = self._resolve_secret_pair(
            "tensorboard_session_secret", "tensorboard_session_secret_file"
        )
        self._resolved_inference_internal_secret = self._resolve_secret_pair(
            "inference_internal_secret", "inference_internal_secret_file"
        )

        if self.app_mode == "production":
            self._validate_production()
        return self

    def _resolve_secret_pair(
        self,
        value_name: str,
        file_name: str,
        *,
        required: bool = False,
    ) -> SecretStr | None:
        direct_value = getattr(self, value_name)
        file_value = getattr(self, file_name)
        direct_was_set = value_name in self.model_fields_set and direct_value is not None

        if direct_was_set and file_value:
            raise ValueError(
                f"{value_name.upper()} and {file_name.upper()} cannot both be set"
            )
        if file_value:
            try:
                resolved_value = Path(file_value).read_text(encoding="utf-8").strip()
            except (OSError, UnicodeError) as error:
                raise ValueError(f"{file_name.upper()} could not be read") from error
            if not resolved_value:
                raise ValueError(f"{file_name.upper()} must not be empty")
            return SecretStr(resolved_value)
        if direct_value is not None:
            return direct_value
        if required:
            raise ValueError(f"{value_name.upper()} is required")
        return None

    def _validate_production(self) -> None:
        self._validate_postgresql_url()
        if self.task_backend != "celery":
            raise ValueError("Production mode requires task_backend=celery")
        if not self._has_secret(self.celery_broker_url):
            raise ValueError("Production mode requires CELERY_BROKER_URL")
        if not self._has_secret(self.redis_events_url):
            raise ValueError("Production mode requires REDIS_EVENTS_URL")
        if self.artifact_storage_backend != "minio":
            raise ValueError("Production mode requires artifact_storage_backend=minio")
        if not self.minio_endpoint or not self.minio_endpoint.strip():
            raise ValueError("Production mode requires MINIO_ENDPOINT")
        if not self.minio_bucket.strip():
            raise ValueError("Production mode requires a non-empty MINIO_BUCKET")
        if not self._has_secret(self.resolved_minio_access_key):
            raise ValueError("Production mode requires MINIO_ACCESS_KEY")
        if not self._has_secret(self.resolved_minio_secret_key):
            raise ValueError("Production mode requires MINIO_SECRET_KEY")
        if not self.mlflow_tracking_uri or not self.mlflow_tracking_uri.strip():
            raise ValueError("Production mode requires MLFLOW_TRACKING_URI")
        if not self._has_secret(self.mlflow_backend_store_uri):
            raise ValueError("Production mode requires MLFLOW_BACKEND_STORE_URI")
        if not self.mlflow_artifact_root or not self.mlflow_artifact_root.strip():
            raise ValueError("Production mode requires MLFLOW_ARTIFACT_ROOT")
        if not self.tensorboard_gateway_url or not self.tensorboard_gateway_url.strip():
            raise ValueError("Production mode requires TENSORBOARD_GATEWAY_URL")
        if not self._has_secret(self.resolved_tensorboard_session_secret):
            raise ValueError("Production mode requires TENSORBOARD_SESSION_SECRET")
        if not self.inference_runtime_url or not self.inference_runtime_url.strip():
            raise ValueError("Production mode requires INFERENCE_RUNTIME_URL")
        if not self._has_secret(self.resolved_inference_internal_secret):
            raise ValueError("Production mode requires INFERENCE_INTERNAL_SECRET")
        if len(self.resolved_inference_internal_secret.get_secret_value()) < 32:
            raise ValueError(
                "Production inference internal secret must contain at least 32 characters"
            )

        jwt_secret = self.resolved_secret_key.get_secret_value()
        if jwt_secret == DEFAULT_SECRET_KEY or len(jwt_secret) < 32:
            raise ValueError(
                "Production secret key must differ from the default and contain at least 32 characters"
            )
        if self.task_hard_timeout_seconds <= self.task_soft_timeout_seconds:
            raise ValueError("Production hard timeout must be greater than soft timeout")

    def _validate_postgresql_url(self) -> None:
        try:
            database_url = make_url(self.database_url)
        except (ArgumentError, ValueError) as error:
            raise ValueError("Production mode requires a valid PostgreSQL URL") from error

        if database_url.drivername not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("Production mode requires a PostgreSQL URL")

        database = unquote(database_url.database or "")
        socket_host = database_url.query.get("host")
        host = database_url.host or (socket_host if isinstance(socket_host, str) else "")
        host = unquote(host)
        if (
            not database
            or any(character.isspace() for character in database)
            or not host
            or any(character.isspace() for character in host)
        ):
            raise ValueError("Production mode requires a complete PostgreSQL URL")

    @staticmethod
    def _has_secret(value: SecretStr | None) -> bool:
        return value is not None and bool(value.get_secret_value().strip())

    def safe_summary(self) -> dict[str, object]:
        return {
            "app_mode": self.app_mode,
            "database_backend": self.database_url.partition(":")[0],
            "database_pool_size": self.database_pool_size,
            "database_max_overflow": self.database_max_overflow,
            "database_pool_timeout_seconds": self.database_pool_timeout_seconds,
            "task_backend": self.task_backend,
            "celery_broker_configured": self._has_secret(self.celery_broker_url),
            "celery_result_backend_configured": self._has_secret(
                self.celery_result_backend
            ),
            "redis_events_configured": self._has_secret(self.redis_events_url),
            "task_soft_timeout_seconds": self.task_soft_timeout_seconds,
            "task_hard_timeout_seconds": self.task_hard_timeout_seconds,
            "artifact_storage_backend": self.artifact_storage_backend,
            "artifact_storage_dir": self.artifact_storage_dir,
            "minio_endpoint": self._sanitize_url(self.minio_endpoint),
            "minio_bucket": self.minio_bucket,
            "minio_access_key_configured": self._has_secret(
                self.resolved_minio_access_key
            ),
            "minio_secret_key_configured": self._has_secret(
                self.resolved_minio_secret_key
            ),
            "minio_secure": self.minio_secure,
            "mlflow_tracking_uri": self._sanitize_url(self.mlflow_tracking_uri),
            "mlflow_backend_store_configured": self._has_secret(
                self.mlflow_backend_store_uri
            ),
            "mlflow_artifact_root": self._sanitize_url(self.mlflow_artifact_root),
            "tensorboard_gateway_url": self._sanitize_url(
                self.tensorboard_gateway_url
            ),
            "tensorboard_session_secret_configured": self._has_secret(
                self.resolved_tensorboard_session_secret
            ),
            "tensorboard_session_ttl_seconds": self.tensorboard_session_ttl_seconds,
            "tensorboard_idle_timeout_seconds": self.tensorboard_idle_timeout_seconds,
            "training_checkpoint_interval_epochs": self.training_checkpoint_interval_epochs,
            "training_stale_after_seconds": self.training_stale_after_seconds,
            "inference_runtime_url": self._sanitize_url(self.inference_runtime_url),
            "inference_internal_secret_configured": self._has_secret(
                self.resolved_inference_internal_secret
            ),
            "inference_conversion_timeout_seconds": self.inference_conversion_timeout_seconds,
            "inference_load_timeout_seconds": self.inference_load_timeout_seconds,
            "inference_predict_timeout_seconds": self.inference_predict_timeout_seconds,
            "inference_rate_limit_capacity": self.inference_rate_limit_capacity,
            "inference_rate_limit_refill_per_second": self.inference_rate_limit_refill_per_second,
            "inference_log_retention_days": self.inference_log_retention_days,
            "inference_rollout_observation_seconds": self.inference_rollout_observation_seconds,
            "jwt_secret_configured": self._has_secret(self.resolved_secret_key),
            "algorithm": self.algorithm,
            "access_token_expire_minutes": self.access_token_expire_minutes,
            "llm_api_url": self._sanitize_url(self.llm_api_url),
            "llm_model": self.llm_model,
            "llm_api_key_configured": bool(self.llm_api_key),
        }

    @staticmethod
    def _sanitize_url(value: str | None) -> str | None:
        if value is None:
            return None
        has_explicit_scheme = "://" in value
        parsed = urlsplit(value if has_explicit_scheme else f"//{value}")
        hostname = parsed.hostname
        if hostname is None:
            return parsed.path
        safe_hostname = f"[{hostname}]" if ":" in hostname else hostname
        try:
            port = parsed.port
        except ValueError:
            port = None
        safe_netloc = f"{safe_hostname}:{port}" if port is not None else safe_hostname
        sanitized = urlunsplit(
            (parsed.scheme, safe_netloc, parsed.path, "", "")
        )
        return sanitized if has_explicit_scheme else sanitized.removeprefix("//")


settings = Settings()
