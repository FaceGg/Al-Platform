# 第五周生产存储与异步任务实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏本地 SQLite/文件/线程模式的前提下，交付 PostgreSQL/Alembic、Redis/Celery、MinIO、制品 URI和生产密钥配置，并用真实 Ubuntu 服务容器完成验收。

**Architecture:** 通过 `Settings`、`ArtifactStorage`、`TaskDispatcher` 和 `RunEventPublisher` 四个边界隔离基础设施。现有 API、SQLAlchemy 模型和 `DAGExecutor` 保持主体结构，工作流执行逻辑从 API 提取为可由本地线程或 Celery Worker 调用的服务。

**Tech Stack:** Python 3.11、FastAPI、Pydantic Settings、SQLAlchemy 2、Alembic、PostgreSQL、Celery、Redis、MinIO、unittest、GitHub Actions。

**Commit policy:** 仓库要求未经用户明确请求不得提交，因此每个任务只列出建议提交检查点；执行时默认不运行 `git commit`。

---

## 文件结构

新增模块按职责拆分：

- `app/config.py`：配置加载、生产模式校验和 Secret 文件解析。
- `app/database.py`：按数据库方言创建 Engine 和 Session。
- `app/database_schema.py`：Alembic revision 检查，不承载迁移写操作。
- `app/storage/`：本地与 MinIO 制品存储实现。
- `app/services/artifact_service.py`：制品元数据事务、权限和存储补偿。
- `app/tasks/`：任务分发、Celery 应用、工作流任务和恢复扫描。
- `app/events/`：本地事件发布与 Redis Pub/Sub 桥接。
- `app/services/workflow_execution.py`：与 API/队列无关的工作流执行服务。
- `app/api/readiness.py`：生产依赖就绪检查。
- `tools/`：SQLite 数据迁移和本地制品迁移命令。
- `tests/integration/`：只在真实服务配置存在时运行的生产集成测试。

## Task 1：扩展第五周测试清单与配置模型

**Files:**
- Modify: `ml-platform/backend/app/config.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`
- Create: `ml-platform/backend/tests/test_config.py`
- Create: `ml-platform/backend/.env.example`

- [x] **Step 1: 先写配置失败测试**

在 `test_config.py` 覆盖以下行为：本地默认值可加载；生产模式拒绝 SQLite、默认 JWT、缺失 Redis/MinIO；`SECRET_KEY` 与 `SECRET_KEY_FILE` 同时存在时报错；Secret 文件内容可读取；`safe_summary()` 不包含密码。

```python
class TestSettings(unittest.TestCase):
    def test_production_rejects_sqlite(self):
        with self.assertRaisesRegex(ValueError, "PostgreSQL"):
            Settings(
                app_mode="production",
                database_url="sqlite:///bad.db",
                secret_key="x" * 32,
                task_backend="celery",
                celery_broker_url="redis://redis:6379/0",
                redis_events_url="redis://redis:6379/1",
                artifact_storage_backend="minio",
                minio_endpoint="minio:9000",
                minio_access_key="access",
                minio_secret_key="secret",
            )

    def test_secret_file_is_resolved_without_leaking_value(self):
        with tempfile.TemporaryDirectory() as directory:
            secret_file = Path(directory) / "jwt"
            secret_file.write_text("s" * 32, encoding="utf-8")
            settings = Settings(secret_key_file=str(secret_file))
            self.assertEqual(settings.resolved_secret_key.get_secret_value(), "s" * 32)
            self.assertNotIn("s" * 32, repr(settings.safe_summary()))
```

- [x] **Step 2: 运行测试并确认 RED**

Run: `python -m unittest tests.test_config -v`
Expected: FAIL，原因是生产字段、Secret 文件和 `safe_summary()` 尚不存在。

- [x] **Step 3: 实现 Settings 与生产校验**

使用字符串 Literal 保持环境变量简单；敏感值使用 `SecretStr`。字段至少包括：

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False,
    )

    app_mode: Literal["local", "production"] = "local"
    database_url: str = "sqlite:///./ml_platform.db"
    secret_key: SecretStr = SecretStr("change-me-in-production")
    secret_key_file: str | None = None
    task_backend: Literal["local", "celery"] = "local"
    celery_broker_url: SecretStr | None = None
    celery_result_backend: SecretStr | None = None
    redis_events_url: SecretStr | None = None
    artifact_storage_backend: Literal["local", "minio"] = "local"
    artifact_storage_dir: str = "./artifact_store"
    minio_endpoint: str | None = None
    minio_bucket: str = "ml-platform"
    minio_access_key: SecretStr | None = None
    minio_access_key_file: str | None = None
    minio_secret_key: SecretStr | None = None
    minio_secret_key_file: str | None = None
    minio_secure: bool = False

    @model_validator(mode="after")
    def validate_runtime(self):
        self._resolve_secret_pairs()
        if self.app_mode == "production":
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("Production mode requires PostgreSQL")
            if self.task_backend != "celery" or self.celery_broker_url is None:
                raise ValueError("Production mode requires Celery")
            if self.artifact_storage_backend != "minio":
                raise ValueError("Production mode requires MinIO")
            if len(self.resolved_secret_key.get_secret_value()) < 32:
                raise ValueError("Production secret key must contain at least 32 characters")
        return self
```

Secret 解析函数必须拒绝同名直接值与文件值同时配置，使用 `Path.read_text(encoding="utf-8").strip()`，并拒绝空文件。

- [x] **Step 4: 建立 `.env.example`**

示例只使用占位文本：

```dotenv
APP_MODE=local
DATABASE_URL=sqlite:///./ml_platform.db
TASK_BACKEND=local
ARTIFACT_STORAGE_BACKEND=local
ARTIFACT_STORAGE_DIR=./artifact_store
# Production secrets should use *_FILE or injected environment variables.
```

- [x] **Step 5: 将新测试唯一归属第五周并验证 GREEN**

在 `WEEK_TEST_MODULES[5]` 添加 `test_config`。
Run: `python -m unittest tests.test_config tests.test_suite_manifest -v`
Expected: PASS。

**建议提交检查点:** `feat: add validated production settings`

## Task 2：建立 Alembic 与方言安全的数据库初始化

**Files:**
- Modify: `ml-platform/backend/requirements.txt`
- Modify: `ml-platform/backend/app/database.py`
- Modify: `ml-platform/backend/app/main.py`
- Create: `ml-platform/backend/alembic.ini`
- Create: `ml-platform/backend/alembic/env.py`
- Create: `ml-platform/backend/alembic/versions/20260715_01_baseline_schema.py`
- Create: `ml-platform/backend/app/database_schema.py`
- Create: `ml-platform/backend/tests/test_database_production.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写数据库模式失败测试**

测试 Engine 参数选择、生产模式不调用 `create_all`、revision 不一致返回稳定错误。

```python
class TestDatabaseProduction(unittest.TestCase):
    def test_sqlite_engine_uses_thread_compatibility(self):
        options = engine_options("sqlite:///test.db")
        self.assertEqual(options["connect_args"], {"check_same_thread": False})

    def test_postgres_engine_enables_pre_ping(self):
        options = engine_options("postgresql+psycopg://user:pass@db/app")
        self.assertTrue(options["pool_pre_ping"])

    def test_outdated_revision_is_not_ready(self):
        self.assertEqual(
            schema_status(current="old", head="new")["code"],
            "DATABASE_SCHEMA_OUTDATED",
        )
```

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_database_production -v`
Expected: FAIL，缺少 `engine_options`、`schema_status` 和 Alembic 配置。

- [x] **Step 3: 增加生产数据库依赖**

在 requirements 增加：

```text
psycopg[binary]==3.2.*
alembic==1.16.*
```

- [x] **Step 4: 实现方言参数和 Schema 检查**

```python
def engine_options(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_pre_ping": True,
        "pool_size": settings.database_pool_size,
        "max_overflow": settings.database_max_overflow,
        "pool_timeout": settings.database_pool_timeout_seconds,
    }
```

`database_schema.py` 使用 Alembic `MigrationContext` 和 `ScriptDirectory` 读取 current/head，只返回 revision 和稳定错误码，不自动升级。

- [x] **Step 5: 初始化 Alembic 并生成静态基线 revision**

Run:

```bash
cd ml-platform/backend
alembic init alembic
alembic revision --autogenerate --rev-id 20260715_01 -m "baseline schema"
```

调整 `env.py` 从 `settings.database_url` 读取连接，并导入全部模型。审查生成 revision，确认包含当前所有表、外键、唯一约束和索引，revision 文件不得在运行时调用 `Base.metadata.create_all()`。

- [x] **Step 6: 修改应用生命周期**

```python
if settings.app_mode == "local":
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility(engine)
else:
    require_current_schema(engine)
```

- [x] **Step 7: 验证本地和空 PostgreSQL 路径**

Run: `python -m unittest tests.test_database_production tests.test_app -v`
Expected: PASS。
Production integration 中再执行真实 `alembic upgrade head`。

**建议提交检查点:** `feat: add alembic-managed postgres schema`

## Task 3：实现 SQLite 到 PostgreSQL 数据迁移命令

**Files:**
- Create: `ml-platform/backend/tools/migrate_database.py`
- Create: `ml-platform/backend/tests/test_database_transfer.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写幂等迁移失败测试**

测试两个隔离 SQLite 数据库以验证通用复制逻辑，再由生产集成测试覆盖 PostgreSQL。

```python
def test_copy_database_preserves_ids_and_is_idempotent(self):
    first = copy_database(self.source_engine, self.target_engine)
    second = copy_database(self.source_engine, self.target_engine)
    self.assertEqual(first["users"].source_count, first["users"].target_count)
    self.assertEqual(second["users"].inserted_count, 0)
```

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_database_transfer -v`
Expected: FAIL，缺少迁移模块。

- [x] **Step 3: 实现反射、排序和内容校验**

核心函数签名固定为：

```python
@dataclass(frozen=True)
class TableTransferResult:
    source_count: int
    target_count: int
    inserted_count: int
    mismatched_ids: tuple[str, ...]

def copy_database(source_engine: Engine, target_engine: Engine) -> dict[str, TableTransferResult]:
    metadata = MetaData()
    metadata.reflect(bind=source_engine)
    results = {}
    for table in metadata.sorted_tables:
        results[table.name] = copy_table(source_engine, target_engine, table)
    return results
```

`copy_table` 按主键读取现有目标记录；相同主键内容不同则加入 `mismatched_ids` 并使 CLI 失败，不覆盖目标数据。

- [x] **Step 4: 实现安全 CLI**

CLI 参数为 `--source-url` 和 `--target-url`，输出脱敏 URL、逐表计数和最终结论。源与目标 URL 相同立即拒绝。任何 mismatch 或计数差异返回退出码 1。

- [x] **Step 5: 运行 GREEN 与重复迁移**

Run: `python -m unittest tests.test_database_transfer -v`
Expected: PASS。

**建议提交检查点:** `feat: add idempotent database transfer tool`

## Task 4：实现 Local/MinIO 存储适配器

**Files:**
- Modify: `ml-platform/backend/requirements.txt`
- Create: `ml-platform/backend/app/storage/__init__.py`
- Create: `ml-platform/backend/app/storage/base.py`
- Create: `ml-platform/backend/app/storage/local.py`
- Create: `ml-platform/backend/app/storage/minio.py`
- Create: `ml-platform/backend/app/storage/factory.py`
- Create: `ml-platform/backend/tests/test_storage.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写 URI、路径安全和完整性失败测试**

```python
def test_local_put_rejects_parent_path(self):
    with self.assertRaises(StorageError):
        self.storage.put(self.source, project_id="p", artifact_id="a", filename="../x")

def test_local_round_trip_preserves_hash(self):
    stored = self.storage.put(self.source, "p", "a", "data.csv")
    self.assertTrue(stored.uri.startswith("file://"))
    self.assertEqual(self.storage.verify(stored.uri, stored.sha256, stored.size), True)
```

MinIO 单元测试使用注入的 fake client，断言 bucket/key、流长度和补偿删除，不访问网络。

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_storage -v`
Expected: FAIL，缺少 storage package。

- [x] **Step 3: 增加 MinIO 依赖并定义协议**

requirements 增加 `minio==7.2.*`。

```python
@dataclass(frozen=True)
class StoredObject:
    uri: str
    size: int
    sha256: str

class ArtifactStorage(Protocol):
    def put(self, source: Path, project_id: str, artifact_id: str, filename: str) -> StoredObject: ...
    def open(self, uri: str) -> BinaryIO: ...
    @contextmanager
    def materialize(self, uri: str) -> Iterator[Path]: ...
    def exists(self, uri: str) -> bool: ...
    def delete(self, uri: str) -> None: ...
    def verify(self, uri: str, sha256: str, size: int) -> bool: ...
```

- [x] **Step 4: 实现 LocalStorage**

路径固定由 base/project/artifact/filename 组成；通过 `Path.resolve()` 验证目标仍在 base 下；写入临时文件后使用同卷原子 rename；返回 `Path.as_uri()`。

- [x] **Step 5: 实现 MinioStorage**

通过构造函数注入 client 和 bucket。`put` 使用 `fput_object` 或已知长度流，key 由服务端生成；`materialize` 下载到 `ML_PLATFORM_TEMP_DIR/artifact-cache` 下的唯一临时目录并在 finally 回收。

- [x] **Step 6: 实现 factory 并验证 GREEN**

```python
def create_artifact_storage(settings: Settings) -> ArtifactStorage:
    if settings.artifact_storage_backend == "local":
        return LocalStorage(Path(settings.artifact_storage_dir))
    return MinioStorage.from_settings(settings)
```

Run: `python -m unittest tests.test_storage -v`
Expected: PASS。

**建议提交检查点:** `feat: add local and minio artifact storage`

## Task 5：迁移 ArtifactService、制品模型和业务调用点

**Files:**
- Modify: `ml-platform/backend/app/models/artifact.py`
- Modify: `ml-platform/backend/app/services/artifact_service.py`
- Modify: `ml-platform/backend/app/api/datasets.py`
- Modify: `ml-platform/backend/app/api/models.py`
- Modify: `ml-platform/backend/app/api/templates.py`
- Modify: `ml-platform/backend/app/api/training.py`
- Modify: `ml-platform/backend/app/services/training_service.py`
- Modify: `ml-platform/backend/tests/test_artifact_service.py`
- Create: `ml-platform/backend/tests/test_artifact_storage_integration.py`
- Create: `ml-platform/backend/alembic/versions/20260715_02_artifact_storage_uri.py`
- Modify: `ml-platform/backend/app/database_migrations.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写存储补偿和旧路径兼容失败测试**

```python
class RecordingStorage:
    def __init__(self, uri: str):
        self.uri = uri
        self.deleted = []

    def put(self, source, project_id, artifact_id, filename):
        return StoredObject(uri=self.uri, size=source.stat().st_size, sha256="digest")

    def delete(self, uri):
        self.deleted.append(uri)

def test_db_failure_deletes_uploaded_object(self):
    storage = RecordingStorage("file:///uploaded/model.bin")
    self.db.commit = Mock(side_effect=RuntimeError("db failed"))
    with self.assertRaises(RuntimeError):
        ArtifactService(self.db, storage).create_from_file(
            project_id=self.project.id,
            source_path=self.source,
            name="model",
            artifact_type="model",
        )
    self.assertEqual(storage.deleted, ["file:///uploaded/model.bin"])

def test_resolve_falls_back_to_legacy_storage_path(self):
    artifact = Artifact(
        project_id=self.project.id,
        name="legacy.csv",
        type="dataset",
        storage_path=str(self.source),
        storage_uri=None,
    )
    self.db.add(artifact)
    self.db.commit()
    with self.service.materialize(artifact.id, artifact.project_id) as path:
        self.assertEqual(path.read_bytes(), self.source.read_bytes())
```

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_artifact_service tests.test_artifact_storage_integration -v`
Expected: FAIL，模型和服务仍只支持 `storage_path`。

- [x] **Step 3: 增加模型字段与双迁移路径**

```python
storage_uri = Column(String(1024), nullable=True, index=True)
```

Alembic revision 添加字段和索引；SQLite 兼容表只增加同名 TEXT 列，作为本地旧数据库过渡，不承担生产迁移。

- [x] **Step 4: 改造 ArtifactService 事务边界**

构造函数改为 `ArtifactService(db: Session, storage: ArtifactStorage)`。创建流程先生成 UUID、上传、创建元数据、commit；commit 异常时 rollback 并调用 storage.delete。`resolve` 只校验数据库归属和类型；真实文件存在性由 storage 处理。

- [x] **Step 5: 更新所有业务调用点**

建立统一依赖：

```python
def get_artifact_service(db: Session = Depends(get_db)) -> ArtifactService:
    return ArtifactService(db, create_artifact_storage(settings))
```

Dataset、Model、Template 和 Training 不再直接读写 `artifact.storage_path`。需要 Path 时必须使用：

```python
with artifact_service.materialize(artifact.id, project_id) as path:
    frame = pd.read_csv(path)
```

- [x] **Step 6: 验证 API 不再拼接制品路径**

Run: `rg -n "artifact\.storage_path|ArtifactService\([^,]+,\s*(Path|os\.path)" ml-platform/backend/app`
Expected: 仅兼容层和迁移工具允许出现 `storage_path`。

- [x] **Step 7: 运行 GREEN**

Run: `python -m unittest tests.test_artifact_service tests.test_artifact_storage_integration tests.test_api_datasets tests.test_training_artifacts -v`
Expected: PASS。

**建议提交检查点:** `feat: route artifacts through storage providers`

## Task 6：持久化 OperatorResult.artifacts 并提供历史制品迁移

**Files:**
- Modify: `ml-platform/backend/app/engine/dag_executor.py`
- Modify: `ml-platform/backend/app/services/artifact_service.py`
- Create: `ml-platform/backend/tools/migrate_artifacts.py`
- Create: `ml-platform/backend/tests/test_operator_artifacts.py`
- Create: `ml-platform/backend/tests/test_artifact_migration.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写 ArtifactDraft 自动持久化失败测试**

注册返回一个 bytes `ArtifactDraft` 的测试算子，执行后断言 ArtifactService 收到 project/run/node 元数据，节点结果包含 artifact ID 和 URI，而不是原始 bytes。

```python
self.assertEqual(saved.metadata["run_id"], "run-1")
self.assertEqual(saved.metadata["node_id"], "node-1")
self.assertEqual(result["artifacts"][0]["artifact_id"], str(saved.id))
```

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_operator_artifacts tests.test_artifact_migration -v`
Expected: FAIL，DAG 尚未消费 `OperatorResult.artifacts`。

- [x] **Step 3: 在 DAGExecutor 统一持久化 drafts**

增加 `_persist_artifacts(result, context)`，仅当 drafts 非空且 `artifact_service/project_id` 可用时执行。每个 draft 调用 `create_from_draft`，返回序列化元数据；任何持久化失败使节点失败，不允许节点完成但制品丢失。

- [x] **Step 4: 实现幂等历史迁移命令**

`migrate_artifacts.py` 查询 `storage_uri IS NULL` 且旧路径存在的记录，上传后校验 size/hash，再在单条事务中更新 URI。支持 `--project-id` 和 `--dry-run`；已迁移记录跳过；失败不清空旧路径。

- [x] **Step 5: 运行 GREEN**

Run: `python -m unittest tests.test_operator_artifacts tests.test_artifact_migration tests.test_operator_contract -v`
Expected: PASS。

**建议提交检查点:** `feat: persist operator artifacts and migrate legacy files`

## Task 7：提取工作流执行服务并建立 Local Dispatcher

**Files:**
- Create: `ml-platform/backend/app/services/workflow_execution.py`
- Create: `ml-platform/backend/app/events/__init__.py`
- Create: `ml-platform/backend/app/events/base.py`
- Create: `ml-platform/backend/app/events/local.py`
- Create: `ml-platform/backend/app/tasks/dispatcher.py`
- Modify: `ml-platform/backend/app/api/runs.py`
- Create: `ml-platform/backend/tests/test_task_dispatcher.py`
- Modify: `ml-platform/backend/tests/test_api_runs.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写 API 分发与执行服务失败测试**

```python
class RecordingDispatcher:
    def __init__(self):
        self.enqueued = []

    def enqueue_workflow(self, run_id: str) -> str:
        self.enqueued.append(run_id)
        return "recorded-task"

def test_start_run_uses_dispatcher(self):
    dispatcher = RecordingDispatcher()
    app.dependency_overrides[get_task_dispatcher] = lambda: dispatcher
    try:
        response = self.client.post(
            f"/api/workflows/{self.workflow_id}/run",
            headers=self.auth_headers,
        )
    finally:
        app.dependency_overrides.pop(get_task_dispatcher, None)
    self.assertEqual(response.status_code, 201)
    self.assertEqual(dispatcher.enqueued, [response.json()["run_id"]])
```

测试 `setUp` 创建用户、项目、包含一个可执行节点的工作流，并设置 `self.workflow_id` 与 `self.auth_headers`。

同时测试 enqueue 失败后 Run 保持 `pending` 并写入 `TASK_ENQUEUE_FAILED` 日志。

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_task_dispatcher tests.test_api_runs -v`
Expected: FAIL，API 仍直接创建 Thread。

- [x] **Step 3: 提取 execute_workflow_run**

将 `_run_workflow` 移入 `workflow_execution.py`：

```python
def execute_workflow_run(
    run_id: str,
    session_factory: sessionmaker = SessionLocal,
    event_publisher: RunEventPublisher | None = None,
) -> None:
    publisher = event_publisher or NullRunEventPublisher()
    db = session_factory()
    try:
        workflow_run = db.query(WorkflowRun).filter(
            WorkflowRun.id == uuid.UUID(run_id),
        ).first()
        if workflow_run is None:
            raise WorkflowExecutionError("RUN_NOT_FOUND", "Workflow run not found")
        _execute_loaded_workflow(db, workflow_run, publisher)
    finally:
        db.close()
```

`_execute_loaded_workflow` 接收已加载的 `WorkflowRun`，包含当前 `_run_workflow` 的 DAG 加载、状态回调、取消和终态写入逻辑；它不得创建数据库会话或访问 FastAPI 全局对象。

同一任务先定义 `RunEventPublisher`、`NullRunEventPublisher` 和 `LocalRunEventPublisher`。Local 实现封装现有 `run_coroutine_threadsafe`，保证执行服务不导入 WebSocket manager。

该服务不导入 FastAPI，不读取 request，不创建线程；所有广播通过 publisher。

- [x] **Step 4: 定义 Dispatcher 与本地实现**

```python
class TaskDispatcher(Protocol):
    def enqueue_workflow(self, run_id: str) -> str: ...
    def cancel(self, task_id: str, terminate: bool = False) -> None: ...
    def get_status(self, task_id: str) -> str: ...

class LocalTaskDispatcher:
    def __init__(self, execute: Callable[[str], None]):
        self.execute = execute

    def enqueue_workflow(self, run_id: str) -> str:
        thread = threading.Thread(target=self.execute, args=(run_id,), daemon=True)
        thread.start()
        return f"local:{thread.ident or run_id}"
```

- [x] **Step 5: API 改为依赖分发器并验证 GREEN**

Run: `python -m unittest tests.test_task_dispatcher tests.test_api_runs tests.test_industrial_template_e2e -v`
Expected: PASS。

**建议提交检查点:** `refactor: isolate workflow execution dispatch`

## Task 8：增加 Celery 任务、领取锁、心跳与取消

**Files:**
- Modify: `ml-platform/backend/app/models/run.py`
- Create: `ml-platform/backend/alembic/versions/20260715_03_workflow_task_metadata.py`
- Modify: `ml-platform/backend/app/database_migrations.py`
- Create: `ml-platform/backend/app/tasks/celery_app.py`
- Create: `ml-platform/backend/app/tasks/workflow_tasks.py`
- Create: `ml-platform/backend/app/tasks/recovery.py`
- Modify: `ml-platform/backend/app/tasks/dispatcher.py`
- Modify: `ml-platform/backend/app/api/runs.py`
- Create: `ml-platform/backend/tests/test_celery_workflows.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写领取幂等、心跳过期和取消失败测试**

```python
def test_fresh_running_task_is_not_claimed_twice(self):
    run = WorkflowRun(
        workflow_id=self.workflow.id,
        status="running",
        task_id="task-1",
        worker_id="worker-1",
        heartbeat_at=utcnow(),
    )
    self.db.add(run)
    self.db.commit()
    self.assertFalse(claim_run(self.db, run.id, "task-2", "worker-2"))

def test_stale_running_task_can_be_reclaimed(self):
    run = WorkflowRun(
        workflow_id=self.workflow.id,
        status="running",
        task_id="task-1",
        worker_id="worker-1",
        heartbeat_at=utcnow() - timedelta(minutes=5),
    )
    self.db.add(run)
    self.db.commit()
    self.assertTrue(claim_run(self.db, run.id, "task-2", "worker-2"))
```

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_celery_workflows -v`
Expected: FAIL，模型字段和 Celery 任务不存在。

- [x] **Step 3: 增加任务元数据字段**

```python
task_id = Column(String(128), nullable=True, index=True)
queue_name = Column(String(64), nullable=True)
worker_id = Column(String(128), nullable=True)
heartbeat_at = Column(DateTime, nullable=True)
```

同步 Alembic 和 SQLite 兼容字段。

- [x] **Step 4: 创建 Celery app**

配置包括：`task_acks_late=True`、`task_reject_on_worker_lost=True`、JSON serializer、UTC、soft/hard time limit、worker prefetch 1。Broker URL 和 result backend 从 Settings Secret 解密后传入，不写日志。

- [x] **Step 5: 实现 claim_run 和工作流任务**

PostgreSQL 查询使用 SQLAlchemy `with_for_update()`；SQLite 本地测试使用普通事务。claim 仅接受 pending、queued 或 stale running。任务领取成功后更新 task/worker/heartbeat，再调用 `execute_workflow_run`。

- [x] **Step 6: 实现恢复扫描与硬超时收敛**

`recover_pending_runs` 重新投递没有 task_id 的 pending/queued；`reconcile_stale_runs` 将超过 hard timeout 且 Celery 无活跃任务的运行标记为 failed，错误码 `TASK_HARD_TIMEOUT`。扫描函数保持幂等。

- [x] **Step 7: 实现取消**

API 先提交 `cancel_requested`，再调用 dispatcher.cancel。Celery Dispatcher 使用 `AsyncResult.revoke(terminate=terminate, signal="SIGTERM")`；Local Dispatcher 仅依赖现有协作取消。

- [x] **Step 8: 运行 GREEN**

Run: `python -m unittest tests.test_celery_workflows tests.test_task_dispatcher tests.test_run_reliability -v`
Expected: PASS。

**建议提交检查点:** `feat: execute workflows with celery`

## Task 9：建立 Redis 事件桥接和 WebSocket 恢复

**Files:**
- Create: `ml-platform/backend/app/events/redis.py`
- Create: `ml-platform/backend/app/events/subscriber.py`
- Modify: `ml-platform/backend/app/main.py`
- Modify: `ml-platform/backend/app/services/workflow_execution.py`
- Create: `ml-platform/backend/tests/test_event_bridge.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写事件序列化、转发和断线恢复失败测试**

测试事件必须包含 `run_id/type`，Redis publisher 使用固定 channel 前缀，订阅器忽略非法 JSON，合法事件转发 manager；REST 返回的终态结果与事件一致。

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_event_bridge -v`
Expected: FAIL，缺少事件接口。

- [x] **Step 3: 实现 Redis publisher**

```python
class RedisRunEventPublisher:
    def __init__(self, client, channel_prefix: str = "ml-platform:runs"):
        self.client = client
        self.channel_prefix = channel_prefix

    def publish(self, run_id: str, payload: dict) -> None:
        event = {**payload, "run_id": run_id}
        self.client.publish(
            f"{self.channel_prefix}:{run_id}",
            json.dumps(event, ensure_ascii=True),
        )
```

Redis 实现发布 JSON 到 `ml-platform:runs:{run_id}`，不得 pickle。

- [x] **Step 4: lifespan 启动异步订阅器**

订阅 pattern `ml-platform:runs:*`，解析 run_id 后调用 WebSocket manager。shutdown 时取消 subscriber task、关闭 Redis client，再 dispose engine。

- [x] **Step 5: 运行 GREEN**

Run: `python -m unittest tests.test_event_bridge tests.test_api_runs -v`
Expected: PASS。

**建议提交检查点:** `feat: bridge celery run events through redis`

## Task 10：增加 readiness 和稳定基础设施错误

**Files:**
- Create: `ml-platform/backend/app/api/readiness.py`
- Create: `ml-platform/backend/app/services/readiness_service.py`
- Modify: `ml-platform/backend/app/main.py`
- Create: `ml-platform/backend/tests/test_readiness.py`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 写分项就绪和脱敏失败测试**

```python
def test_readiness_reports_component_codes_without_secrets(self):
    result = readiness_service.check_all()
    encoded = json.dumps(result)
    self.assertNotIn("db-password", encoded)
    self.assertEqual(result["database"]["code"], "DATABASE_UNAVAILABLE")
```

- [x] **Step 2: 运行并确认 RED**

Run: `python -m unittest tests.test_readiness -v`
Expected: FAIL，路由和服务不存在。

- [x] **Step 3: 实现检查器**

数据库执行 `SELECT 1` 并检查 Alembic；Redis 执行 ping；Celery 执行 inspect ping 并要求至少一个 worker；MinIO 检查 bucket 存在。每个检查限制超时并映射稳定错误码。

- [x] **Step 4: 注册路由并保持 health 兼容**

`GET /api/health` 继续返回 `{"status": "ok"}`。`GET /api/ready` 在全部通过时返回 200，否则返回 503 和分项状态。

- [x] **Step 5: 运行 GREEN**

Run: `python -m unittest tests.test_readiness tests.test_app -v`
Expected: PASS。

**建议提交检查点:** `feat: add production readiness checks`

## Task 11：建立真实 PostgreSQL/Redis/MinIO/Celery 集成测试

**Files:**
- Create: `ml-platform/backend/tests/test_production_stack.py`
- Create: `ml-platform/backend/tools/run_production_integration.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `ml-platform/backend/tests/week_manifest.py`

- [x] **Step 1: 编写生产集成验收脚本**

测试仅在 `RUN_PRODUCTION_INTEGRATION=1` 时运行，否则明确 skip。覆盖：Alembic upgrade 两次、核心 CRUD、MinIO round trip、Celery 工作流完成、重复投递、取消、软超时、过期心跳恢复和 readiness。

- [x] **Step 2: 本地运行并确认环境门禁**

将 `test_production_stack` 加入第五周清单。
Run: `python -m unittest tests.test_production_stack -v`
Expected: SKIP，消息为 `RUN_PRODUCTION_INTEGRATION is not enabled`，而不是连接失败。

- [x] **Step 3: 增加 Ubuntu production-integration job**

Job 使用 PostgreSQL 16、Redis 7 和 MinIO 服务容器；安装后端依赖和 CPU PyTorch；执行 Alembic；后台启动 Celery worker；最后运行集成测试。敏感值使用 job 级测试环境变量，不写入仓库。

关键环境变量：

```yaml
env:
  APP_MODE: production
  DATABASE_URL: postgresql+psycopg://postgres:test-password@127.0.0.1:5432/ml_platform
  TASK_BACKEND: celery
  CELERY_BROKER_URL: redis://127.0.0.1:6379/0
  REDIS_EVENTS_URL: redis://127.0.0.1:6379/1
  ARTIFACT_STORAGE_BACKEND: minio
  MINIO_ENDPOINT: 127.0.0.1:9000
  MINIO_BUCKET: ml-platform-test
  RUN_PRODUCTION_INTEGRATION: "1"
```

Secret key 和 MinIO credentials 使用 GitHub job env 中的测试值，并确保测试日志脱敏。

- [x] **Step 4: 上传失败证据**

失败时上传 Celery、API 和 migration 日志；上传前运行脱敏扫描，发现测试密码或 Secret 时使 job 失败且不上传原日志。

- [ ] **Step 5: 验证远程 job**

Run: 推送分支或更新 PR 后等待 `production-integration`。
Expected: PostgreSQL、Redis、MinIO、Celery 全部健康，集成测试退出码 0。

**建议提交检查点:** `ci: verify production infrastructure stack`

## Task 12：更新容器、启动方式与迁移文档

**Files:**
- Modify: `docker-compose.yml`
- Modify: `ml-platform/backend/Dockerfile`
- Create: `ml-platform/backend/Dockerfile.worker`
- Modify: `ml-platform/USAGE.md`
- Modify: `docs/baseline/BUILD_AND_TEST.md`
- Modify: `docs/baseline/FEATURE_INVENTORY.md`
- Modify: `docs/baseline/TECHNICAL_DEBT.md`
- Create: `docs/delivery/PRODUCTION_INFRASTRUCTURE.md`
- Create: `docs/delivery/DATABASE_MIGRATION.md`
- Create: `docs/delivery/ARTIFACT_MIGRATION.md`
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `PLATFORM_STATUS.md`

- [x] **Step 1: 更新 Compose 为双模式生产栈**

增加 postgres、redis、minio、minio-init 和 worker；backend/worker 共享相同生产环境配置，不挂载本地 artifact_store；服务健康检查通过后再启动依赖服务。开发脚本继续默认本地模式。

- [x] **Step 2: 修正 Docker 健康检查与 Worker 镜像**

Backend HEALTHCHECK 请求 `/api/health`；Worker 使用相同代码和依赖，命令固定为：

```dockerfile
CMD ["celery", "-A", "app.tasks.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
```

- [x] **Step 3: 编写部署、迁移和回滚说明**

文档必须给出：配置清单、Secret 文件示例、`alembic upgrade head`、SQLite 数据迁移、Artifact dry-run/执行、切换顺序、回滚到 SQLite/Local/Thread、常见错误码和日志位置。不得写真实密码。

- [ ] **Step 4: 更新项目状态但不提前标记完成**

只有 production-integration 和全部本地回归均通过后，才把第五周从“进行中”改为“已完成”。否则记录具体未完成项和恢复命令。

**建议提交检查点:** `docs: add production infrastructure operations guide`

## Task 13：执行第五周完整验收与收尾

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [x] **Step 1: 执行第五周聚焦测试**

Run: `python run_suite.py --week 5`
Expected: 第五周全部模块通过；生产集成模块在本地明确 skip。

- [x] **Step 2: 执行后端全量测试**

Run: `python run_suite.py`
Expected: 第一至第五周所有模块通过，无失败模块。

- [x] **Step 3: 执行前端与浏览器回归**

Run:

```bash
cd ml-platform/frontend
npm test
npm run build
npx playwright test --project=chromium
npm audit --registry=https://registry.npmjs.org
```

Expected: 现有 35 个前端测试全部通过；构建成功；Chromium 1/1；0 漏洞。

- [x] **Step 4: 验证迁移与安全扫描**

Run:

```bash
alembic upgrade head
alembic current
rg -n "change-me-in-production|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}" . --glob '!docs/superpowers/**'
git diff --check
```

Expected: revision 为 head；正式文件无真实凭据；diff check 通过。

- [ ] **Step 5: 确认远程生产集成结果**

记录 GitHub Actions Run URL、Ubuntu job 结论、PostgreSQL/Redis/MinIO/Celery 版本和关键测试计数。远程 job 未通过时不得标记第五周完成。

- [x] **Step 6: 清理生成物并更新文档**

清理 `temp_test` 下本轮数据库、MinIO 下载缓存、测试日志和构建产物，保留 `.gitkeep` 与约定缓存。向开发计划末尾追加问题、根因、解决、验证和遗留事项；向共享经验文档追加可复用经验。

- [x] **Step 7: 最终工作区检查**

Run: `git status --short`
Expected: 只包含本次范围和用户原有修改；不得回退或混入未知文件。

**建议提交检查点:** `feat: complete week 5 production infrastructure`
