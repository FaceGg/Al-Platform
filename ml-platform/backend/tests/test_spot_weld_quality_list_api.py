"""Spot-weld quality run list API contract tests (A-17).

Locks the run-list pagination contract (``limit``/``offset`` + ``total``)
and the prefetched serialization path: project/creator names come from one
outerjoin, sample counts from one grouped COUNT — the list path must never
touch ``run.samples`` (which would drag the three JSON payload columns of
every sample row into memory).
"""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.artifact import Artifact
from app.models.project import Project
from app.models.spot_weld_quality import SpotWeldQualityRun, SpotWeldQualitySample
from app.models.user import User


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


_BASE_TIME = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)


def _run(db, *, project, user, artifact, index, created_at, samples=0, input_fingerprint=None):
    run = SpotWeldQualityRun(
        project_id=project.id,
        dataset_artifact_id=artifact.id,
        created_by_id=user.id,
        status="completed",
        input_fingerprint=input_fingerprint if input_fingerprint is not None else {},
        created_at=created_at,
    )
    db.add(run)
    db.flush()
    for sample_index in range(samples):
        db.add(SpotWeldQualitySample(
            run_id=run.id,
            source_row_index=sample_index,
            display_id=f"row-{sample_index}",
            current_label="ok" if sample_index == 0 else None,
        ))
    db.commit()
    return run


@pytest.fixture()
def workspace(db):
    user = User(username=f"weld-{uuid.uuid4().hex[:8]}", password_hash="hash")
    db.add(user)
    db.flush()
    project = Project(name=f"质量项目-{uuid.uuid4().hex[:6]}", owner_id=user.id)
    db.add(project)
    db.flush()
    artifact = Artifact(
        project_id=project.id,
        name="weld-dataset",
        type="dataset",
        storage_path=f"uploads/{uuid.uuid4().hex}.csv",
    )
    db.add(artifact)
    db.commit()
    return db, user, project, artifact


def test_run_list_is_offset_paginated_with_total(workspace):
    db, user, project, artifact = workspace
    from app.api.auth import get_current_user
    from app.database import get_db
    from app.main import app

    for index in range(5):
        _run(db, project=project, user=user, artifact=artifact, index=index,
             created_at=_BASE_TIME.replace(minute=index))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        first = client.get(f"/api/projects/{project.id}/spot-weld/runs", params={"limit": 2})
        assert first.status_code == 200
        body = first.json()
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 0
        assert len(body["items"]) == 2
        # 最新创建的在前（created_at desc）
        assert body["items"][0]["created_at"] > body["items"][1]["created_at"]

        second = client.get(f"/api/projects/{project.id}/spot-weld/runs", params={"limit": 2, "offset": 2})
        assert second.json()["total"] == 5
        assert len(second.json()["items"]) == 2

        tail = client.get(f"/api/projects/{project.id}/spot-weld/runs", params={"limit": 2, "offset": 4})
        assert len(tail.json()["items"]) == 1
        for bad in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
            assert client.get(f"/api/projects/{project.id}/spot-weld/runs", params=bad).status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_run_list_serialization_matches_prefetched_context_without_sample_rows(workspace):
    """列表路径零 run.samples 行加载：样本数走一次分组 COUNT，名字走 outerjoin。"""
    db, user, project, artifact = workspace
    from app.api.auth import get_current_user
    from app.api.spot_weld_quality import _serialize_run
    from app.database import get_db
    from app.main import app

    rich = _run(db, project=project, user=user, artifact=artifact, index=0,
                created_at=_BASE_TIME, samples=3)
    plain = _run(db, project=project, user=user, artifact=artifact, index=1,
                 created_at=_BASE_TIME.replace(minute=1))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    sample_table_selects: list[str] = []

    def _count_sample_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "spot_weld_quality_samples" in statement and statement.lstrip().upper().startswith("SELECT"):
            sample_table_selects.append(statement)

    engine = db.get_bind()
    event.listen(engine, "after_cursor_execute", _count_sample_selects)
    try:
        client = TestClient(app)
        response = client.get(f"/api/projects/{project.id}/spot-weld/runs")
        assert response.status_code == 200
        items = {item["id"]: item for item in response.json()["items"]}
    finally:
        event.remove(engine, "after_cursor_execute", _count_sample_selects)
        app.dependency_overrides.clear()

    rich_item = items[str(rich.id)]
    assert rich_item["project_name"] == project.name
    assert rich_item["created_by_name"] == user.username
    # statistics/input_fingerprint 均无行数 → 回落分组 COUNT=3
    assert rich_item["sample_count"] == 3
    assert rich_item["annotation_progress"]["total_count"] == 3
    # 无样本的 run：COUNT 分组无行 → 0
    assert items[str(plain.id)]["sample_count"] == 0
    # 整页对样本表的 SELECT 恰好一次（分组 COUNT）；旧实现逐行 len(run.samples)
    assert len(sample_table_selects) == 1, len(sample_table_selects)

    # 预取序列化与单条详情序列化共享键逐字段相等
    detail_payload = _serialize_run(rich, include_results=False)
    for key in ("project_name", "created_by_name", "sample_count", "annotation_progress"):
        assert rich_item[key] == detail_payload[key], key


def test_run_list_surfaces_manual_annotation_counts(workspace):
    db, user, project, artifact = workspace
    from app.api.auth import get_current_user
    from app.database import get_db
    from app.main import app

    manual = _run(
        db, project=project, user=user, artifact=artifact, index=0,
        created_at=_BASE_TIME, samples=4,
        input_fingerprint={"label_mode": "manual"},
    )
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        response = client.get(f"/api/projects/{project.id}/spot-weld/runs")
        item = next(i for i in response.json()["items"] if i["id"] == str(manual.id))
        assert item["label_mode"] == "manual"
        assert item["annotation_progress"]["annotated_count"] == 1
        assert item["annotation_progress"]["total_count"] == 4
    finally:
        app.dependency_overrides.clear()


def test_all_runs_route_paginates_and_scopes_to_accessible_projects(workspace):
    db, user, project, artifact = workspace
    from app.api.auth import get_current_user
    from app.database import get_db
    from app.main import app

    mine = _run(db, project=project, user=user, artifact=artifact, index=0,
                created_at=_BASE_TIME)
    # 他人项目：不可见
    stranger = User(username=f"other-{uuid.uuid4().hex[:8]}", password_hash="hash")
    db.add(stranger)
    db.flush()
    other_project = Project(name="other", owner_id=stranger.id)
    db.add(other_project)
    db.flush()
    other_artifact = Artifact(
        project_id=other_project.id, name="other", type="dataset", storage_path="uploads/other.csv",
    )
    db.add(other_artifact)
    db.flush()
    _run(db, project=other_project, user=stranger, artifact=other_artifact, index=9,
         created_at=_BASE_TIME.replace(minute=9))
    db.commit()

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        client = TestClient(app)
        page = client.get("/api/spot-weld/runs", params={"limit": 10})
        assert page.status_code == 200
        body = page.json()
        assert body["total"] == 1
        assert [item["id"] for item in body["items"]] == [str(mine.id)]
        assert body["limit"] == 10 and body["offset"] == 0
        scoped = client.get("/api/spot-weld/runs", params={"project_id": str(project.id)})
        assert scoped.json()["total"] == 1
    finally:
        app.dependency_overrides.clear()
