"""Application configuration via pydantic-settings."""

from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit, urlunsplit

from cryptography.fernet import Fernet
from pydantic import AliasChoices, Field, PrivateAttr, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


# 历史默认值仅本地开发回退；生产校验拒绝（_validate_production_settings）
_HISTORIC_DEFAULT_ANNOTATOR_SECRET = "-".join(
    ("change", "me", "annotator", "service", "secret")
)
DEFAULT_ANNOTATOR_SERVICE_SECRET = _HISTORIC_DEFAULT_ANNOTATOR_SECRET
# pydantic 私有属性名（Settings 内引用同一默认值）
DEFAULT_SECRET_KEY = "-".join(("change", "me", "in", "production"))


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
    # 引导管理员初始口令：只从环境变量 ML_PLATFORM_ADMIN_INITIAL_PASSWORD 读取
    # （显式 alias——字段名默认映射 ADMIN_INITIAL_PASSWORD，与 compose/CI/installer
    # 的变量名不一致曾导致 CI 净栈解析不到），源码/示例/测试不落真实凭据；
    # production 未配置时启动引导 fail-closed（见 main.ensure_default_admin），
    # local/CI 回退开发口令保持夹具兼容。
    admin_initial_password: SecretStr | None = Field(
        default=None, repr=False, exclude=True,
        validation_alias="ML_PLATFORM_ADMIN_INITIAL_PASSWORD",
    )
    frontend_origin: str = "http://localhost:5173"
    frontend_origin_aliases: str = ""
    annotator_public_origin: str = "http://localhost:8443"
    annotator_api_origin: str = "http://localhost:8000"
    annotator_port: int = Field(default=8443, ge=1, le=65535)
    annotator_session_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    annotator_service_issuer: str = "ml-platform-annotator"
    annotator_service_audience: str = "ml-platform-internal"
    annotator_service_algorithm: str = "HS256"
    annotator_service_secret: SecretStr = Field(
        default=SecretStr(DEFAULT_ANNOTATOR_SERVICE_SECRET), exclude=True,
        # 部署侧 env 名与字段名不一致，显式 alias（同 admin_initial_password 教训）；
        # AliasChoices 保留字段名传参（测试/内部构造）
        validation_alias=AliasChoices("annotator_service_secret", "ANNOTATOR_SERVICE_SECRET"),
    )
    login_ip_rate_limit_capacity: int = Field(default=5, ge=1, le=100)
    # 登录账号维度限流容量（默认 10/15min）：e2e 全量套件以同一账号顺序登录
    # 13+ 次，必须能经 env 放开（playwright webServer 注入 100）
    login_account_rate_limit_capacity: int = Field(default=10, ge=1, le=100)

    @property
    def resolved_annotator_service_secret(self) -> SecretStr:
        return self.annotator_service_secret

    task_backend: Literal["local", "celery"] = "local"
    celery_broker_url: SecretStr | None = Field(default=None, exclude=True)
    celery_result_backend: SecretStr | None = Field(default=None, exclude=True)
    redis_events_url: SecretStr | None = Field(default=None, exclude=True)
    task_soft_timeout_seconds: int = Field(default=3600, gt=0)
    task_hard_timeout_seconds: int = Field(default=3900, gt=0)
    # Agent 运行心跳陈旧阈值：超过该秒数未刷新心跳的 running 行会被
    # 启动期恢复扫描标记为失败（AGENT_RUN_INTERRUPTED）。
    agent_run_stale_after_seconds: int = Field(default=600, ge=60)

    # 闭环「智能体重训模式」护栏：项目内重放并发上限（跨部署资源护栏）/
    # 重放轮询超时（LLM S1 实测 >60s、超时地板 240s，全流程按小时留量）/
    # 轮次终态冷却分钟（agent 模式）/ 24h 滚动窗口熔断次数（触顶转人工）。
    agent_retrain_project_concurrency: int = Field(default=2, ge=1)
    agent_retrain_poll_max_age_seconds: int = Field(default=7200, ge=600)
    agent_retrain_cooldown_minutes: int = Field(default=30, ge=0)
    agent_retrain_daily_limit: int = Field(default=3, ge=1)

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
    training_redispatch_after_seconds: int = Field(default=60, ge=30, le=86400)
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
    # 推理结果明细（B1-16，技术方案 §3）：三项独立于 inference_log_retention_days。
    # 评审确认点 2 默认值：日量上限 20 万行（0=不限）、快照采样 1%、保留 90 天。
    inference_result_retention_days: int = Field(default=90, ge=1, le=3650)
    inference_result_daily_cap: int = Field(default=200_000, ge=0)
    inference_snapshot_sample_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    # 预警规则平台默认（F2a/D14）：场景 alert_settings 缺省时生效。触发下限
    # 独立于分级阈值（路线 B1-01 对标反面教材——竞品 47.5% 置信度即发预警）。
    quality_alert_trigger_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    quality_alert_high_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    quality_alert_critical_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    quality_alert_sla_hours: int = Field(default=24, ge=1, le=24 * 30)
    quality_alert_merge_window_minutes: int = Field(default=30, ge=1, le=1440)
    # 漂移监控（B1-09，技术方案 §9C D38–D40）：扫描周期、窗口、最小样本、分级阈值与
    # 数据质量阈值都可配。漂移是触发器不是自动开关——严重级只通知，不自动处置。
    drift_scan_interval_seconds: int = Field(default=300, ge=30, le=86400)
    drift_window_hours: int = Field(default=24, ge=1, le=24 * 30)
    drift_min_samples: int = Field(default=200, ge=10)
    drift_severe_psi: float = Field(default=0.25, ge=0.0)
    drift_watch_psi: float = Field(default=0.10, ge=0.0)
    drift_missing_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    drift_constant_share: float = Field(default=0.999, ge=0.5, le=1.0)
    drift_psi_bins: int = Field(default=10, ge=2, le=50)
    drift_baseline_max_rows: int = Field(default=50_000, ge=100)
    drift_baseline_min_samples: int = Field(default=100, ge=10)
    # 单次推理请求累计特征直方图的样本上限（0 = 不限）：限的是落库线程的单次工作量
    inference_histogram_max_records: int = Field(default=2000, ge=0)

    annotation_max_samples: int = Field(default=1_000_000, ge=1, le=10_000_000)
    annotation_max_input_columns: int = Field(default=200, ge=1, le=2_000)
    annotation_max_label_columns: int = Field(default=20, ge=1, le=200)

    kubernetes_endpoint_allowlist: list[str] = Field(default_factory=list)
    kubernetes_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    kubernetes_read_timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    kubernetes_stale_after_seconds: int = Field(default=300, ge=10, le=86400)
    kubernetes_allow_insecure_endpoints: bool = False
    kubernetes_job_approved_image_prefixes: list[str] = Field(default_factory=list)
    kubernetes_job_allowed_env_keys: list[str] = Field(default_factory=list)
    kubernetes_job_max_cpu_cores: int = Field(default=4, ge=1, le=64)
    kubernetes_job_max_memory_gb: int = Field(default=8, ge=1, le=128)
    kubernetes_job_max_timeout_seconds: int = Field(default=3600, ge=30, le=86400)
    kubernetes_job_log_chunk_bytes: int = Field(default=262144, ge=1024, le=1048576)
    kubernetes_job_ttl_seconds_finished: int = Field(default=3600, ge=60, le=604800)
    notebook_default_idle_seconds: int = Field(default=3600, ge=60, le=86400)
    notebook_max_per_user: int = Field(default=4, ge=1, le=64)
    notebook_access_token_ttl_seconds: int = Field(default=900, ge=30, le=3600)
    notebook_container_port: int = Field(default=8888, ge=1, le=65535)
    gpu_snapshot_stale_seconds: int = Field(default=300, ge=30, le=86400)
    image_build_approved: bool = False
    image_build_builder_image: str = ""
    governance_snapshot_interval_seconds: int = Field(default=60, ge=30, le=3600)
    governance_snapshot_stale_seconds: int = Field(default=300, ge=60, le=86400)
    governance_snapshot_retention_seconds: int = Field(default=86400, ge=3600, le=604800)
    governance_usage_max_per_scope: int = Field(default=100, ge=10, le=1000)

    notification_master_key: SecretStr | None = Field(default=None, exclude=True)
    notification_master_key_file: str | None = Field(
        default=None, repr=False, exclude=True
    )
    # 外部数据源口令加密主密钥（B1-08/D8）：独立于通知/LLM 密钥隔离爆炸半径；
    # 三把主密钥共用一个轮换工具（tools/rotate_fernet_keys.py）
    datasource_master_key: SecretStr | None = Field(default=None, exclude=True)
    datasource_master_key_file: str | None = Field(
        default=None, repr=False, exclude=True
    )
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: SecretStr | None = Field(default=None, exclude=True)
    smtp_password: SecretStr | None = Field(default=None, exclude=True)
    smtp_from: str | None = None
    smtp_use_tls: bool = True
    notification_max_payload_bytes: int = Field(default=65536, ge=1024, le=1048576)
    notification_delivery_max_attempts: int = Field(default=5, ge=1, le=20)
    notification_webhook_timeout_seconds: int = Field(default=10, ge=1, le=30)
    notification_webhook_allowlist: Annotated[list[str], NoDecode] = Field(
        default_factory=list
    )

    # LLM / RAG settings
    llm_api_url: str = Field(
        default="https://api.openai.com/v1/chat/completions",
        repr=False,
        exclude=True,
    )
    llm_api_key: str = Field(default="", repr=False, exclude=True)
    llm_model: str = "gpt-3.5-turbo"
    # Master key encrypting LLMProfile API keys at rest (spec v0.9 §14.1).
    llm_master_key: SecretStr | None = Field(default=None, exclude=True)
    # 文件变体对齐通知/数据源密钥形制（D8：纳入生产校验）
    llm_master_key_file: str | None = Field(default=None, repr=False, exclude=True)

    # Knowledge-graph auto extraction limits (rules + statistics pipeline).
    # Entity/relation caps of 0 mean unlimited: storage keeps every candidate
    # above min frequency; the graph page view layer decides what to render.
    knowledge_graph_max_entities: int = 0
    knowledge_graph_max_relations: int = 0
    knowledge_graph_min_entity_freq: int = 2
    knowledge_graph_time_budget_seconds: float = 30
    # 字符预算是极端防线（防止超大库长时间占用），真实超时保护是上面的
    # time_budget（内部截断+truncated 标记）。此前 200000 过于保守——
    # 5 文档 1.15M 字符的普通库直接 422（2026-11-19 用户实测「开发计划」库）
    knowledge_graph_max_extract_chars: int = 2000000

    # 五阶段 KG 流水线：LLM 深度抽取与图存储投影。llm 通道复用平台 LLM
    # 网关（resolve_profile(purpose="kg_extraction")），未配档案/Key 时任务
    # fail-closed 报错而不是静默退回规则层。max_chunks 是成本护栏：超出部分
    # 按 chunk 顺序延后到下一次任务（断点续抽天然分批）。
    kg_llm_max_chunks: int = 120
    kg_llm_time_budget_seconds: int = 7200
    kg_llm_max_tokens: int = 3000
    kg_llm_batch_chars: int = 2400
    # 单任务内 LLM 抽取并发度：默认 1（串行）。出口实测结论（2026-11-20/23
    # 两轮）：同一来源的并发 LLM 请求会被直接拒绝——流式并发≥3 卡死 SSE body
    # （200 头到达 body 不结束）、非流式并发 2 秒回空响应，只有串行稳定。
    # 单分片加速靠输出压缩（每片实体≤10）；出口修复后可再评估并发。
    kg_llm_concurrency: int = 1
    # 非流式通道开关：出口对 SSE 流式干扰严重时（LLMStreamStalled 大面积出现）
    # 走一次性 POST 等完整 JSON 的非流式通道（2026-11-23 实测可用）；False=流式
    kg_llm_use_nonstream: bool = True
    # 融合模糊候选的相似度阈值（difflib SequenceMatcher ratio）
    kg_fusion_fuzzy_threshold: float = 0.92
    # Neo4j 图存储投影：空 URI = 投影层禁用（图查询走 PG 兜底，功能不缺只慢）
    neo4j_uri: str | None = None
    neo4j_user: str = "neo4j"
    neo4j_password: SecretStr | None = Field(default=None, exclude=True)

    # Retrieval tokenization: switch off to fall back to the legacy
    # TfidfVectorizer word splitting (also requires a reembed afterwards).
    retrieval_use_jieba: bool = True

    # Python script operator runtime: scripts execute in an isolated subprocess
    # against a persistent venv (docker named volume). Missing imports declared
    # in the script are auto-installed via pip from server-configured sources
    # only; users never specify packages or index URLs. Empty venv_dir disables
    # the venv and runs against the current interpreter (tests / local runs /
    # CI default); production compose injects PYTHON_SCRIPT_VENV_DIR explicitly.
    python_script_venv_dir: str = ""
    python_script_pip_sources: str = (
        "https://pypi.org/simple,"
        "https://mirrors.aliyun.com/pypi/simple/,"
        "https://pypi.tuna.tsinghua.edu.cn/simple"
    )
    python_script_auto_install: bool = True
    python_script_timeout_seconds: int = 300
    python_script_install_timeout_seconds: int = 900

    _resolved_secret_key: SecretStr = PrivateAttr()
    _resolved_minio_access_key: SecretStr | None = PrivateAttr(default=None)
    _resolved_minio_secret_key: SecretStr | None = PrivateAttr(default=None)
    _resolved_tensorboard_session_secret: SecretStr | None = PrivateAttr(default=None)
    _resolved_inference_internal_secret: SecretStr | None = PrivateAttr(default=None)
    _resolved_notification_master_key: SecretStr | None = PrivateAttr(default=None)

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

    @property
    def resolved_notification_master_key(self) -> SecretStr | None:
        return self._resolved_notification_master_key

    @property
    def resolved_datasource_master_key(self) -> SecretStr | None:
        return self._resolved_datasource_master_key

    @property
    def resolved_llm_master_key(self) -> SecretStr | None:
        return self._resolved_llm_master_key

    @field_validator("notification_webhook_allowlist", mode="before")
    @classmethod
    def normalize_notification_webhook_allowlist(cls, value):
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

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
        self._resolved_notification_master_key = self._resolve_secret_pair(
            "notification_master_key", "notification_master_key_file"
        )
        self._resolved_datasource_master_key = self._resolve_secret_pair(
            "datasource_master_key", "datasource_master_key_file"
        )
        self._resolved_llm_master_key = self._resolve_secret_pair(
            "llm_master_key", "llm_master_key_file"
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
        if not self._has_secret(self.resolved_notification_master_key):
            raise ValueError("Production mode requires NOTIFICATION_MASTER_KEY")
        try:
            Fernet(
                self.resolved_notification_master_key.get_secret_value().encode("ascii")
            )
        except (UnicodeEncodeError, ValueError) as error:
            raise ValueError("Production NOTIFICATION_MASTER_KEY must be a valid Fernet key") from error
        # 三把 Fernet 主密钥同形校验（D8）：数据源口令与 LLM 档案密钥纳入生产门
        if not self._has_secret(self.resolved_datasource_master_key):
            raise ValueError("Production mode requires DATASOURCE_MASTER_KEY")
        try:
            Fernet(
                self.resolved_datasource_master_key.get_secret_value().encode("ascii")
            )
        except (UnicodeEncodeError, ValueError) as error:
            raise ValueError("Production DATASOURCE_MASTER_KEY must be a valid Fernet key") from error
        if not self._has_secret(self.resolved_llm_master_key):
            raise ValueError("Production mode requires LLM_MASTER_KEY")
        try:
            Fernet(
                self.resolved_llm_master_key.get_secret_value().encode("ascii")
            )
        except (UnicodeEncodeError, ValueError) as error:
            raise ValueError("Production LLM_MASTER_KEY must be a valid Fernet key") from error

        jwt_secret = self.resolved_secret_key.get_secret_value()
        if jwt_secret == DEFAULT_SECRET_KEY or len(jwt_secret) < 32:
            raise ValueError(
                "Production secret key must differ from the default and contain at least 32 characters"
            )
        if self.task_hard_timeout_seconds <= self.task_soft_timeout_seconds:
            raise ValueError("Production hard timeout must be greater than soft timeout")
        annotator_secret = self.resolved_annotator_service_secret.get_secret_value()
        if (
            annotator_secret == _HISTORIC_DEFAULT_ANNOTATOR_SECRET
            or len(annotator_secret) < 32
        ):
            raise ValueError(
                "Production ANNOTATOR_SERVICE_SECRET must differ from the default "
                "and contain at least 32 characters"
            )

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
            "training_redispatch_after_seconds": self.training_redispatch_after_seconds,
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
            "notification_master_key_configured": self._has_secret(
                self.resolved_notification_master_key
            ),
            "smtp_host_configured": bool(self.smtp_host and self.smtp_host.strip()),
            "smtp_username_configured": self._has_secret(self.smtp_username),
            "smtp_password_configured": self._has_secret(self.smtp_password),
            "smtp_from_configured": bool(self.smtp_from and self.smtp_from.strip()),
            "smtp_use_tls": self.smtp_use_tls,
            "notification_max_payload_bytes": self.notification_max_payload_bytes,
            "notification_delivery_max_attempts": self.notification_delivery_max_attempts,
            "notification_webhook_timeout_seconds": self.notification_webhook_timeout_seconds,
            "notification_webhook_allowlist_count": len(
                self.notification_webhook_allowlist
            ),
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
