"""Quality domain API tests: CRUD + permission matrix + validation (B1-10).

覆盖（技术方案 §11.1 test_quality_domain.py 行）：
- 场景/工位/规格 CRUD 往返与级联删除；
- 权限矩阵：quality.manage 写动词 × 四角色（owner/editor 过、
  operator/viewer 403、非成员 404），读动词 viewer 可读；
- field_roles 角色键合法性与一列一角色约束；
- 绑定部署的 condition_column 一致性；
- 工位设备绑定的「设备属于当前用户」校验（D6 限界）；
- 规格统计量枚举与 uq (scene_id, field, statistic) 唯一性；
- edge_devices 影子两列随 ORM 生效（诚实设计⑤预留）。
"""
import uuid
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, get_db
from app.main import app
from app.models.access import ProjectMember
from app.models.artifact import Artifact
from app.models.compute import EdgeDevice
from app.models.model_registry import (
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project
from app.models.quality_domain import (
    QualityScene,
    QualitySpecLimit,
    QualityStation,
)
from app.models.user import User


class TestQualityDomainAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        # 与 conftest 生产语义对齐：SQLite 夹具库同样强制外键
        # （场景级联删除依赖 DB 端 ON DELETE CASCADE，PG 生产如此）
        @event.listens_for(cls.engine, "connect")
        def _set_sqlite_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        Base.metadata.create_all(cls.engine)
        cls.db = cls.Session()

        cls.users = {
            role: User(username=f"quality-{role}", password_hash="hash")
            for role in ("owner", "editor", "operator", "viewer",
                         "outsider", "deviceowner")
        }
        cls.db.add_all(cls.users.values())
        cls.db.flush()
        cls.project = Project(name="Quality domain project", owner_id=cls.users["owner"].id)
        cls.other_project = Project(name="Quality other project", owner_id=cls.users["outsider"].id)
        cls.db.add_all([cls.project, cls.other_project])
        cls.db.flush()
        for role in ("editor", "operator", "viewer"):
            cls.db.add(ProjectMember(
                project_id=cls.project.id,
                user_id=cls.users[role].id,
                role=role,
                created_by=cls.users["owner"].id,
            ))
        cls.db.flush()

        # 真实模型注册链（FK 强制下 InferenceDeployment 需要可解析的
        # model_version_id；artifact 双引用同行复用 onnx_artifact 形态）
        artifact = Artifact(
            project_id=cls.project.id,
            name="quality-domain-deploy-artifact",
            type="model",
            storage_path="quality-domain/deploy.joblib",
        )
        cls.db.add(artifact)
        cls.db.flush()
        registered = RegisteredModel(
            project_id=cls.project.id, name="quality-domain-model",
        )
        cls.db.add(registered)
        cls.db.flush()
        version = ModelVersion(
            registered_model_id=registered.id,
            version_number=1,
            source_kind="onnx_artifact",
            source_artifact_id=artifact.id,
            onnx_artifact_id=artifact.id,
        )
        cls.db.add(version)
        cls.db.flush()

        def _make_deployment(project, name, condition_column):
            dep_artifact = Artifact(
                project_id=project.id,
                name=f"{name}-artifact",
                type="model",
                storage_path=f"quality-domain/{name}.joblib",
            )
            cls.db.add(dep_artifact)
            cls.db.flush()
            dep_registered = RegisteredModel(
                project_id=project.id, name=f"{name}-model",
            )
            cls.db.add(dep_registered)
            cls.db.flush()
            dep_version = ModelVersion(
                registered_model_id=dep_registered.id,
                version_number=1,
                source_kind="onnx_artifact",
                source_artifact_id=dep_artifact.id,
                onnx_artifact_id=dep_artifact.id,
            )
            cls.db.add(dep_version)
            cls.db.flush()
            deployment = InferenceDeployment(
                project_id=project.id,
                name=name,
                model_version_id=dep_version.id,
                condition_column=condition_column,
            )
            cls.db.add(deployment)
            return deployment

        cls.deployment = _make_deployment(cls.project, "quality-deploy", "station_id")
        cls.foreign_deployment = _make_deployment(
            cls.other_project, "quality-deploy-other", "station_id",
        )
        cls.own_device = EdgeDevice(
            name="own-device", owner_id=cls.users["owner"].id,
        )
        cls.other_device = EdgeDevice(
            name="other-device", owner_id=cls.users["deviceowner"].id,
        )
        cls.db.add_all([cls.own_device, cls.other_device])
        cls.db.commit()

        cls.current_user = cls.users["owner"]
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def setUp(self):
        self.__class__.current_user = self.users["owner"]

    # ------------------------------------------------------------ helpers

    def _create_scene(self, code="S1", **overrides):
        payload = {
            "code": code,
            "name": f"Scene {code}",
            "field_roles": {"sample_key": "vin", "target": "ng"},
        }
        payload.update(overrides)
        response = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes", json=payload,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _create_station(self, scene_id, code="ST1", **overrides):
        payload = {"code": code, "name": f"Station {code}", "scene_id": str(scene_id)}
        payload.update(overrides)
        response = self.client.post(
            f"/api/projects/{self.project.id}/quality-stations", json=payload,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _create_spec(self, scene_id, field="torque", statistic="value", **overrides):
        payload = {
            "field": field,
            "statistic": statistic,
            "usl": 1.5,
            "lsl": 0.5,
            "target": 1.0,
            "unit": "N*m",
        }
        payload.update(overrides)
        response = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes/{scene_id}/spec-limits",
            json=payload,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    # -------------------------------------------------------------- CRUD

    def test_scene_crud_roundtrip(self):
        before = self.client.get(f"/api/projects/{self.project.id}/quality-scenes")
        total_before = before.json()["total"]
        scene = self._create_scene()
        self.assertEqual(scene["code"], "S1")
        self.assertEqual(scene["field_roles"], {"sample_key": "vin", "target": "ng"})

        listed = self.client.get(f"/api/projects/{self.project.id}/quality-scenes")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], total_before + 1)

        detail = self.client.get(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}"
        )
        self.assertEqual(detail.status_code, 200, detail.text)

        updated = self.client.put(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}",
            json={"name": "Scene renamed", "description": "updated"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["name"], "Scene renamed")

        replaced = self.client.put(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/field-roles",
            json={"field_roles": {"batch": "lot_no"}},
        )
        self.assertEqual(replaced.status_code, 200, replaced.text)
        self.assertEqual(replaced.json()["field_roles"], {"batch": "lot_no"})

        cleared = self.client.put(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/field-roles",
            json={"field_roles": {}},
        )
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertEqual(cleared.json()["field_roles"], {})

        deleted = self.client.delete(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}"
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)
        gone = self.client.get(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}"
        )
        self.assertEqual(gone.status_code, 404, gone.text)

    def test_scene_code_conflict_rejected(self):
        self._create_scene(code="DUP")
        response = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes",
            json={"code": "DUP", "name": "dup"},
        )
        self.assertEqual(response.status_code, 409, response.text)
        # 同 code 不同项目互不影响（other_project 的 owner 是 outsider）
        self.__class__.current_user = self.users["outsider"]
        ok = self.client.post(
            f"/api/projects/{self.other_project.id}/quality-scenes",
            json={"code": "DUP", "name": "dup"},
        )
        self.assertEqual(ok.status_code, 201, ok.text)
        self.__class__.current_user = self.users["owner"]

    def test_scene_delete_cascades_stations_and_specs(self):
        scene = self._create_scene(code="CAS")
        station = self._create_station(scene["id"], code="CAS-ST")
        spec = self._create_spec(scene["id"], field="casc")
        response = self.client.delete(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}"
        )
        self.assertEqual(response.status_code, 204, response.text)
        self.assertIsNone(
            self.db.query(QualityStation).filter(QualityStation.id == uuid.UUID(station["id"])).first()
        )
        self.assertIsNone(
            self.db.query(QualitySpecLimit).filter(QualitySpecLimit.id == uuid.UUID(spec["id"])).first()
        )

    # ------------------------------------------------------ 权限矩阵

    def _reset_fixtures(self):
        """权限矩阵用：清空并重建一套场景/工位/规格夹具（ORM 直建）。"""
        self.db.query(QualitySpecLimit).delete()
        self.db.query(QualityStation).delete()
        self.db.query(QualityScene).filter(
            QualityScene.project_id == self.project.id,
        ).delete(synchronize_session=False)
        self.db.commit()
        scene = QualityScene(
            project_id=self.project.id, code="PERM", name="perm",
        )
        self.db.add(scene)
        self.db.flush()
        station = QualityStation(
            scene_id=scene.id, code="PERM-ST", name="perm-st",
        )
        spec = QualitySpecLimit(
            scene_id=scene.id, field="perm", statistic="value", usl=1.0,
        )
        self.db.add_all([station, spec])
        self.db.commit()
        return scene, station, spec

    def test_write_permission_matrix(self):
        # 动词按依赖排序：删除类放最后（场景删除会级联掉工位与规格）
        def write_verbs_builder(scene, station, spec):
            base = f"/api/projects/{self.project.id}"
            return [
                ("post", f"{base}/quality-scenes",
                 {"code": "PERM-NEW", "name": "x"}, (200, 201)),
                ("put", f"{base}/quality-scenes/{scene.id}",
                 {"name": "renamed"}, (200,)),
                ("put", f"{base}/quality-scenes/{scene.id}/field-roles",
                 {"field_roles": {"target": "ng"}}, (200,)),
                ("post", f"{base}/quality-stations",
                 {"code": "PERM-ST-NEW", "name": "x", "scene_id": str(scene.id)},
                 (200, 201)),
                ("put", f"{base}/quality-stations/{station.id}",
                 {"name": "renamed"}, (200,)),
                ("post", f"{base}/quality-scenes/{scene.id}/spec-limits",
                 {"field": "perm-new", "statistic": "value"}, (200, 201)),
                ("put", f"{base}/quality-scenes/{scene.id}/spec-limits/{spec.id}",
                 {"usl": 2.0}, (200,)),
                ("delete", f"{base}/quality-scenes/{scene.id}/spec-limits/{spec.id}",
                 None, (204,)),
                ("delete", f"{base}/quality-stations/{station.id}",
                 None, (204,)),
                ("delete", f"{base}/quality-scenes/{scene.id}",
                 None, (204,)),
            ]
        # owner/editor 过（quality.manage），operator/viewer 403，非成员 404
        expectations = {
            "owner": None, "editor": None,
            "operator": (403,), "viewer": (403,), "outsider": (404,),
        }
        for role, expected in expectations.items():
            scene, station, spec = self._reset_fixtures()
            self.__class__.current_user = self.users[role]
            for method, url, body, success in write_verbs_builder(scene, station, spec):
                if body is None:
                    response = getattr(self.client, method)(url)
                else:
                    response = getattr(self.client, method)(url, json=body)
                if expected is None:
                    self.assertIn(response.status_code, success, response.text)
                else:
                    self.assertIn(response.status_code, expected, response.text)
        self.__class__.current_user = self.users["owner"]

    def test_read_access_viewer_allowed_outider_not(self):
        scene = self._create_scene(code="READ")
        self.__class__.current_user = self.users["viewer"]
        for url in (
            f"/api/projects/{self.project.id}/quality-scenes",
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}",
            f"/api/projects/{self.project.id}/quality-stations",
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/spec-limits",
        ):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
        self.__class__.current_user = self.users["outsider"]
        response = self.client.get(f"/api/projects/{self.project.id}/quality-scenes")
        self.assertEqual(response.status_code, 404, response.text)
        self.__class__.current_user = self.users["owner"]

    # ---------------------------------------------------- field_roles 校验

    def test_field_roles_validation(self):
        bad_role = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes",
            json={"code": "FR1", "name": "x",
                  "field_roles": {"unknown_role": "col"}},
        )
        self.assertEqual(bad_role.status_code, 422, bad_role.text)

        duplicate_column = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes",
            json={"code": "FR2", "name": "x",
                  "field_roles": {"sample_key": "vin", "batch": "vin"}},
        )
        self.assertEqual(duplicate_column.status_code, 422, duplicate_column.text)

        empty_column = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes",
            json={"code": "FR3", "name": "x", "field_roles": {"target": "  "}},
        )
        self.assertEqual(empty_column.status_code, 422, empty_column.text)

        unknown_key = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes",
            json={"code": "FR4", "name": "x", "unexpected": True},
        )
        self.assertEqual(unknown_key.status_code, 422, unknown_key.text)

    # ------------------------------------------------ 部署绑定一致性

    def test_deployment_binding_consistency(self):
        # 跨项目部署 → 404
        foreign = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes",
            json={"code": "DP1", "name": "x",
                  "deployment_id": str(self.foreign_deployment.id)},
        )
        self.assertEqual(foreign.status_code, 404, foreign.text)

        # 不存在的部署 → 404
        missing = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes",
            json={"code": "DP2", "name": "x",
                  "deployment_id": str(uuid.uuid4())},
        )
        self.assertEqual(missing.status_code, 404, missing.text)

        # 工况列不一致 → 422（部署声明 station_id）
        mismatch = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes",
            json={"code": "DP3", "name": "x",
                  "deployment_id": str(self.deployment.id),
                  "condition_column": "oven_zone"},
        )
        self.assertEqual(mismatch.status_code, 422, mismatch.text)

        # 一致 → 201；场景未声明工况列 → 允许绑定
        matched = self._create_scene(
            code="DP4", deployment_id=str(self.deployment.id),
            condition_column="station_id",
        )
        self.assertEqual(matched["deployment_id"], str(self.deployment.id))
        undeclared = self._create_scene(
            code="DP5", deployment_id=str(self.deployment.id),
        )
        self.assertEqual(undeclared["deployment_id"], str(self.deployment.id))

        # 更新路径：把已绑定场景的工况列改成不一致值 → 422
        conflict = self.client.put(
            f"/api/projects/{self.project.id}/quality-scenes/{matched['id']}",
            json={"condition_column": "oven_zone"},
        )
        self.assertEqual(conflict.status_code, 422, conflict.text)

    # ------------------------------------------------------ 工位与设备

    def test_station_crud_and_device_binding(self):
        scene = self._create_scene(code="ST-D")
        station = self._create_station(
            scene["id"], factory="F1", workshop="W1", production_line="L1",
            edge_device_id=str(self.own_device.id),
        )
        self.assertEqual(station["edge_device_id"], str(self.own_device.id))
        self.assertTrue(station["enabled"])

        listed = self.client.get(
            f"/api/projects/{self.project.id}/quality-stations",
            params={"scene_id": str(scene["id"])},
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)

        updated = self.client.put(
            f"/api/projects/{self.project.id}/quality-stations/{station['id']}",
            json={"workshop": "W2", "enabled": False},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["workshop"], "W2")
        self.assertFalse(updated.json()["enabled"])

        # 非本人设备 → 422；不存在设备 → 404
        not_owned = self.client.post(
            f"/api/projects/{self.project.id}/quality-stations",
            json={"code": "ST-X", "name": "x", "scene_id": str(scene["id"]),
                  "edge_device_id": str(self.other_device.id)},
        )
        self.assertEqual(not_owned.status_code, 422, not_owned.text)
        missing = self.client.post(
            f"/api/projects/{self.project.id}/quality-stations",
            json={"code": "ST-Y", "name": "x", "scene_id": str(scene["id"]),
                  "edge_device_id": str(uuid.uuid4())},
        )
        self.assertEqual(missing.status_code, 404, missing.text)

        deleted = self.client.delete(
            f"/api/projects/{self.project.id}/quality-stations/{station['id']}"
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)

    def test_station_code_conflict_within_scene_only(self):
        scene_a = self._create_scene(code="STCA")
        scene_b = self._create_scene(code="STCB")
        self._create_station(scene_a["id"], code="SHARED")
        # 同场景同 code → 409；不同场景同 code → 允许
        conflict = self.client.post(
            f"/api/projects/{self.project.id}/quality-stations",
            json={"code": "SHARED", "name": "x", "scene_id": str(scene_a["id"])},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        ok = self._create_station(scene_b["id"], code="SHARED")
        self.assertEqual(ok["code"], "SHARED")

    # ------------------------------------------------------ 规格定义

    def test_spec_limit_crud_and_uniqueness(self):
        scene = self._create_scene(code="SPEC")
        spec = self._create_spec(scene["id"], field="torque", statistic="value")
        self.assertEqual(spec["statistic"], "value")

        # 同 field+statistic → 409；同 field 不同 statistic → 允许（E27 波形统计量）
        conflict = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/spec-limits",
            json={"field": "torque", "statistic": "value", "usl": 2.0},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)
        mean_spec = self._create_spec(scene["id"], field="torque", statistic="mean")
        self.assertEqual(mean_spec["statistic"], "mean")

        invalid_statistic = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/spec-limits",
            json={"field": "torque", "statistic": "median"},
        )
        self.assertEqual(invalid_statistic.status_code, 422, invalid_statistic.text)

        crossed = self.client.post(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/spec-limits",
            json={"field": "amp", "statistic": "value", "usl": 0.5, "lsl": 1.5},
        )
        self.assertEqual(crossed.status_code, 422, crossed.text)

        updated = self.client.put(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/spec-limits/{spec['id']}",
            json={"usl": 1.8},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["usl"], 1.8)

        listed = self.client.get(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/spec-limits",
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 2)

        deleted = self.client.delete(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/spec-limits/{spec['id']}",
        )
        self.assertEqual(deleted.status_code, 204, deleted.text)

    def test_spec_limit_update_statistic_conflict(self):
        scene = self._create_scene(code="SPCU")
        self._create_spec(scene["id"], field="f1", statistic="value")
        spec2 = self._create_spec(scene["id"], field="f2", statistic="mean")
        # 把 f2 的统计量改成 value 会撞上 f1 的 (f1, value)？不——键含 field，
        # (f2, value) 不存在 → 允许。再造 (f2, value) 后改 f2.mean→value 才冲突。
        self._create_spec(scene["id"], field="f2", statistic="value")
        conflict = self.client.put(
            f"/api/projects/{self.project.id}/quality-scenes/{scene['id']}/spec-limits/{spec2['id']}",
            json={"statistic": "value"},
        )
        self.assertEqual(conflict.status_code, 409, conflict.text)

    # ------------------------------------------------------ 模型层冒烟

    def test_edge_device_shadow_columns_present(self):
        # 诚实设计⑤预留：两列随 ORM 生效，F1 不读写
        columns = {column.name for column in EdgeDevice.__table__.columns}
        self.assertIn("shadow_desired", columns)
        self.assertIn("shadow_reported", columns)

    def test_field_role_keys_constant_matches_contract(self):
        from app.schemas.quality_domain import validate_field_roles

        with self.assertRaises(ValueError):
            validate_field_roles({"nope": "col"})
        validated = validate_field_roles({"target": " ng "})
        self.assertEqual(validated, {"target": "ng"})
