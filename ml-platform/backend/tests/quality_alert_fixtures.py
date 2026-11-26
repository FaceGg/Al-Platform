"""补齐路线第一批 F2（预警处置）测试的公共夹具。

内存 SQLite + 应用端点（TestClient）+ 项目内三角色（owner / operator /
viewer）。不以 test_ 开头，不会被当成测试模块收集。
"""
import unittest
import uuid
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.access import ProjectMember
from app.models.data_version import DatasetSample, DatasetVersion
from app.models.project import Project
from app.models.quality_alerts import QualityAlert
from app.models.quality_domain import QualityScene, QualityStation
from app.models.user import User


class QualityAlertApiCase(unittest.TestCase):
    """端点级夹具：cls.client 走应用路由，cls.db 直连同一个内存库。"""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.db = cls.Session()
        tag = uuid.uuid4().hex[:6]
        cls.owner = User(username=f"qa-owner-{tag}", password_hash="hash")
        cls.operator = User(username=f"qa-operator-{tag}", password_hash="hash")
        cls.viewer = User(username=f"qa-viewer-{tag}", password_hash="hash")
        cls.assignee = User(username=f"qa-assignee-{tag}", password_hash="hash")
        cls.db.add_all([cls.owner, cls.operator, cls.viewer, cls.assignee])
        cls.db.flush()
        cls.project = Project(name=f"Quality alerts {tag}", owner_id=cls.owner.id)
        cls.db.add(cls.project)
        cls.db.flush()
        cls.db.add_all([
            ProjectMember(project_id=cls.project.id, user_id=cls.operator.id, role="operator"),
            ProjectMember(project_id=cls.project.id, user_id=cls.viewer.id, role="viewer"),
        ])
        cls.scene = QualityScene(
            project_id=cls.project.id, code="WELD", name="点焊场景",
            field_roles={"sample_key": "vin", "target": "quality", "time": "ts"},
        )
        cls.db.add(cls.scene)
        cls.db.flush()
        cls.station = QualityStation(
            scene_id=cls.scene.id, code="ST-1", name="一号工位",
            factory="F1", workshop="W1", production_line="L1",
        )
        cls.db.add(cls.station)
        cls.db.commit()
        cls.actor = cls.owner
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.actor
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def setUp(self):
        # 上一条用例失败时可能留下未提交的半截状态：先丢弃，再让对象重新加载
        self.db.rollback()
        self.db.expire_all()
        # 同类用例共用一个内存库：合并键等业务键必须带每条用例独立的键，
        # 否则前一条用例留下的行会被后一条的查询命中
        self.case_key = uuid.uuid4().hex[:8]
        self.addCleanup(setattr, type(self), "actor", self.owner)

    def act_as(self, user):
        """切换当前请求的用户。依赖注入读的是类属性，必须设在类上而不是实例上。"""
        type(self).actor = user

    def make_dataset_version(self, rows, **version_fields):
        """造一个就绪的数据集版本；rows 是按行序排列的字典列表。

        行里有 "vin" 键时用它作 sample_id，否则用行号——复核任务与曲线叠加
        都按 sample_id 找行。version_fields 在创建时写入（数据集版本表组不可变，
        建好后不能改）。
        """
        latest = self.db.query(DatasetVersion.version).filter(
            DatasetVersion.project_id == self.project.id,
        ).order_by(DatasetVersion.version.desc()).first()
        columns = sorted({key for row in rows for key in row})
        version = DatasetVersion(
            project_id=self.project.id,
            operator_id=self.owner.id,
            version=(int(latest[0]) if latest else 0) + 1,
            status="ready",
            row_count=len(rows),
            column_count=len(columns),
            content_hash=uuid.uuid4().hex,
            schema_hash=uuid.uuid4().hex,
            **version_fields,
        )
        self.db.add(version)
        self.db.flush()
        for index, row in enumerate(rows):
            self.db.add(DatasetSample(
                dataset_version_id=version.id,
                sample_id=str(row.get("vin", f"row-{index}")),
                row_index=index,
                values=dict(row),
            ))
        self.db.commit()
        return version

    def make_alert(self, **overrides) -> QualityAlert:
        """直接造一条预警（绕开产生器，专测处置链路）。"""
        now = datetime.utcnow()
        payload = dict(
            project_id=self.project.id,
            scene_id=self.scene.id,
            station_id=self.station.id,
            source_type="model_risk",
            severity="warning",
            title="测试预警",
            evidence={"kind": "model_risk", "score": 0.9},
            merge_key="model_risk:deployment=test",
            sla_due_at=now + timedelta(hours=24),
            last_event_at=now,
            created_at=now,
            updated_at=now,
        )
        payload.update(overrides)
        alert = QualityAlert(**payload)
        self.db.add(alert)
        self.db.flush()
        # 与产生器一致：新预警带一条 created 轨迹
        from app.services import quality_alerts as service

        service.append_event(self.db, alert, "created", created_at=payload["created_at"])
        self.db.commit()
        return alert

    def ack(self, alert_id, assignee_id=None):
        return self.client.post(
            f"/api/projects/{self.project.id}/quality-alerts/{alert_id}/ack",
            json={"assignee_id": str(assignee_id or self.assignee.id)},
        )

    def transition(self, alert_id, to_status, **extra):
        return self.client.post(
            f"/api/projects/{self.project.id}/quality-alerts/{alert_id}/transition",
            json={"to_status": to_status, **extra},
        )

    def detail(self, alert_id):
        return self.client.get(
            f"/api/projects/{self.project.id}/quality-alerts/{alert_id}"
        ).json()

    def events(self, alert_id):
        return self.detail(alert_id)["events"]
