from pathlib import Path


def test_task_2_migration_precedes_generic_task_revisions():
    versions = Path(__file__).parents[1] / "alembic" / "versions"
    data_version = (versions / "20260902_15_generic_data_versions.py").read_text(
        encoding="utf-8",
    )
    generic_tasks = (versions / "20260903_15_generic_annotation_tasks.py").read_text(
        encoding="utf-8",
    )
    owner_idempotency = (
        versions / "20260904_16_generic_task_owner_idempotency.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "20260829_14"' in data_version
    assert 'down_revision = "20260902_15"' in generic_tasks
    assert 'down_revision = "20260903_15"' in owner_idempotency
