from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.operation import DurableOperation
from app.models.platform_models import AnnotationTaskExecutionStatistic, AnnotationTaskPreview
from app.models.project import Project
from app.models.user import User
from app.services.annotation_task_state import list_annotation_execution_stats


def test_execution_statistics_migration_backfills_inline_operation_summary(tmp_path):
    backend_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "annotation-execution-statistics.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config(str(backend_root / "alembic.ini"))
    original_database_url = settings.database_url
    settings.database_url = database_url
    engine = None
    try:
        command.upgrade(config, "20260916_47")
        engine = create_engine(database_url)
        session = sessionmaker(bind=engine, expire_on_commit=False)()
        try:
            user = User(username=f"statistics-migration-{uuid.uuid4().hex}", password_hash="hash")
            session.add(user)
            session.flush()
            project = Project(name="Statistics migration", owner_id=user.id)
            session.add(project)
            session.flush()
            task_id = uuid.uuid4()
            legacy_annotation_tasks = sa.table(
                "generic_annotation_tasks",
                sa.column("id", sa.Uuid()),
                sa.column("project_id", sa.Uuid()),
                sa.column("dataset_version_id", sa.Uuid()),
                sa.column("label_schema_id", sa.Uuid()),
                sa.column("owner_id", sa.Uuid()),
                sa.column("mode"),
                sa.column("status"),
                sa.column("task_revision"),
                sa.column("sample_scope", sa.JSON()),
                sa.column("label_snapshot", sa.JSON()),
                sa.column("task_snapshot", sa.JSON()),
            )
            session.execute(legacy_annotation_tasks.insert().values(
                id=task_id,
                project_id=project.id,
                dataset_version_id=uuid.uuid4(),
                label_schema_id=uuid.uuid4(),
                owner_id=user.id,
                mode="automatic",
                status="awaiting_annotation",
                task_revision=0,
                sample_scope={"kind": "all"},
                label_snapshot={},
                task_snapshot={},
            ))
            preview = AnnotationTaskPreview(
                task_id=task_id, task_revision=0, config_hash="sha256:migration-preview",
                status="completed", progress=100, created_by=user.id,
            )
            session.add(preview)
            session.flush()
            session.execute(DurableOperation.__table__.insert().values(
                id=preview.operation_id,
                resource_key=f"annotation-preview:{preview.id}",
                idempotency_key=preview.config_hash,
                state="completed", stage="completed", progress=100, attempt=1,
            ))
            operation_id = uuid.uuid4()
            session.execute(DurableOperation.__table__.insert().values(
                id=operation_id,
                resource_key=f"annotation-execution:{task_id}",
                idempotency_key=f"0:{preview.id}",
                state="completed",
                stage="completed",
                progress=100,
                attempt=1,
                result_summary={
                    "sample_count": 2,
                    "needs_review_count": 0,
                    "stats": {
                        "cluster": [{"key": "1", "cluster_id": 1, "count": 2}],
                        "rule": [
                            {"key": "r-1", "rule_id": "r-1", "count": 2},
                            {"key": "r-2", "rule_id": "r-2", "count": 1},
                        ],
                        "final_label": [{"key": "label=a", "label": "label", "value": "a", "count": 2}],
                    },
                },
            ))
            session.commit()
            user_id, project_id = user.id, project.id
            preview_id, preview_operation_id = preview.id, preview.operation_id
        finally:
            session.close()
            engine.dispose()
            engine = None

        command.upgrade(config, "head")
        command.upgrade(config, "head")
        engine = create_engine(database_url)
        with sessionmaker(bind=engine)() as session:
            for identifier, resource_type in (
                (operation_id, "annotation_execution"), (preview_operation_id, "annotation_preview"),
            ):
                operation = session.get(DurableOperation, identifier)
                assert (operation.task_id, operation.project_id, operation.preview_id, operation.resource_type) == (
                    task_id, project_id, preview_id, resource_type,
                )
            rows = session.query(AnnotationTaskExecutionStatistic).filter_by(operation_id=operation_id).all()
            assert {(row.task_id, row.kind, row.payload["key"], row.count) for row in rows} == {
                (task_id, "cluster", "1", 2),
                (task_id, "rule", "r-1", 2),
                (task_id, "rule", "r-2", 1),
                (task_id, "final_label", "label=a", 2),
            }
            for row in rows:
                assert session.query(AnnotationTaskExecutionStatistic).filter_by(id=row.id).one().id == row.id
            assert session.get(DurableOperation, operation_id).result_summary == {
                "sample_count": 2, "needs_review_count": 0,
            }
            first = list_annotation_execution_stats(session, task_id, operation_id, user_id, kind="rule", limit=1)
            second = list_annotation_execution_stats(
                session, task_id, operation_id, user_id, kind="rule", limit=1, cursor=first["next_cursor"],
            )
            assert first["items"] == [{"key": "r-1", "rule_id": "r-1", "count": 2}]
            assert second["items"] == [{"key": "r-2", "rule_id": "r-2", "count": 1}]
            assert second["next_cursor"] is None
    finally:
        if engine is not None:
            engine.dispose()
        settings.database_url = original_database_url
