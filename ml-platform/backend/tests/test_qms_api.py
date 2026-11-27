"""第三批 QMS API 级测试（技术方案 §3）：8D 证据包导出+下载、批次概览聚合、
质量报告 HTML/JSON 导出。

服务层口径见 test_qms_t1 / test_qms_t2_t3；本模块覆盖端点层（TestClient +
quality_alert_fixtures 端点级夹具）。
"""
import json
import tempfile
import uuid
import zipfile
from io import BytesIO

from app.config import settings
from app.models.qms import QmsTraceLink
from app.services.qms_core import create_d8, create_ncr
from app.services.qms_tools import generate_report
from tests.quality_alert_fixtures import QualityAlertApiCase


class QmsApiCase(QualityAlertApiCase):
    """质量 API 端点级夹具 + 8D 证据包所需的本地工件存储目录。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._storage_dir = tempfile.TemporaryDirectory()
        cls._original_storage_dir = settings.artifact_storage_dir
        settings.artifact_storage_dir = cls._storage_dir.name

    @classmethod
    def tearDownClass(cls):
        settings.artifact_storage_dir = cls._original_storage_dir
        cls._storage_dir.cleanup()
        super().tearDownClass()


class TestD8Evidence(QmsApiCase):
    def test_evidence_export_and_download(self):
        ncr = create_ncr(self.db, project_id=self.project.id,
                         code=f"NCR-EV-{self.case_key}", title="证据链",
                         created_by_id=self.owner.id)
        d8 = create_d8(self.db, project_id=self.project.id,
                       code=f"D8-EV-{self.case_key}", title="8D 证据链",
                       ncr_id=ncr.id, created_by_id=self.owner.id)
        self.db.commit()
        response = self.client.post(
            f"/api/projects/{self.project.id}/qms/d8/{d8.id}/evidence")
        self.assertEqual(response.status_code, 200, response.text)
        artifact_id = response.json()["artifact_id"]
        self.assertIn("/evidence-exports/", response.json()["download"])
        download = self.client.get(
            f"/api/projects/{self.project.id}/evidence-exports/{artifact_id}/download")
        self.assertEqual(download.status_code, 200, download.text)
        archive = zipfile.ZipFile(BytesIO(download.content))
        self.assertIn("d8_evidence.json", archive.namelist())
        self.assertIn("MANIFEST.SHA256", archive.namelist())
        payload = json.loads(archive.read("d8_evidence.json").decode("utf-8"))
        self.assertEqual(payload["d8_report"]["code"], d8.code)
        self.assertEqual(payload["ncr"]["stage"], "draft")


class TestTraceBatch(QmsApiCase):
    def test_batch_overview_aggregates_objects(self):
        from app.models.quality_alerts import QualityAlert

        batch = f"B-{self.case_key}"
        self.db.add(QualityAlert(
            project_id=self.project.id, source_type="model_risk",
            severity="warning", title="批次预警", evidence={},
            merge_key=f"tb-{self.case_key}", batch_no=batch,
        ))
        self.db.add(QmsTraceLink(project_id=self.project.id,
                                 sample_key=f"S-{self.case_key}-1", batch_no=batch))
        self.db.add(QmsTraceLink(project_id=self.project.id,
                                 sample_key=f"S-{self.case_key}-2", batch_no=batch))
        self.db.commit()
        response = self.client.get(
            f"/api/projects/{self.project.id}/qms/trace-batch/{batch}")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["batch_no"], batch)
        self.assertEqual(data["sample_count"], 2)
        self.assertEqual(len(data["alerts"]), 1)


class TestReportExport(QmsApiCase):
    def test_report_exports_html_and_json(self):
        report = generate_report(self.db, project_id=self.project.id,
                                 period="daily", period_key="20261126")
        self.db.commit()
        html = self.client.get(
            f"/api/projects/{self.project.id}/qms/quality-reports/{report.id}/export.html")
        self.assertEqual(html.status_code, 200, html.text)
        self.assertIn("text/html", html.headers["content-type"])
        self.assertIn("attachment", html.headers["content-disposition"])
        self.assertIn("质量报告", html.text)
        blob = self.client.get(
            f"/api/projects/{self.project.id}/qms/quality-reports/{report.id}/export.json")
        self.assertEqual(blob.status_code, 200, blob.text)
        payload = json.loads(blob.text)
        self.assertEqual(payload["period"], "daily")
        self.assertIn("ng_rate", payload["content"])

    def test_report_export_not_found(self):
        response = self.client.get(
            f"/api/projects/{self.project.id}/qms/quality-reports/{uuid.uuid4()}/export.json")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "QMS_REPORT_NOT_FOUND")


class TestListEndpoints(QmsApiCase):
    def test_group_lists_return_created_rows(self):
        from app.models.qms import QmsFmea
        from app.services.qms_tools import (
            create_or_replace_plan,
            normalize_fmea_items,
            record_iqc,
        )

        tag = self.case_key
        supplier_id = self.client.post(
            f"/api/projects/{self.project.id}/qms/suppliers",
            json={"code": f"SUP-{tag}", "name": "供应商"},
        ).json()["id"]
        self.client.post(
            f"/api/projects/{self.project.id}/qms/iqc-records",
            json={"supplier_id": supplier_id, "arrival_count": 10,
                  "inspected_count": 10, "defect_count": 2},
        )
        plan = create_or_replace_plan(self.db, project_id=self.project.id,
                                      code=f"CP-{tag}", quality_points=[])
        self.db.add(QmsFmea(project_id=self.project.id, name=f"FMEA-{tag}",
                            items=normalize_fmea_items([
                                {"failure_mode": "a", "severity": 2,
                                 "occurrence": 2, "detection": 2},
                            ])))
        self.db.commit()
        plan_id = str(plan.id)
        d8 = self.client.post(
            f"/api/projects/{self.project.id}/qms/d8",
            json={"code": f"D8-L-{tag}", "title": "列表"},
        ).json()["id"]
        self.client.post(
            f"/api/projects/{self.project.id}/qms/msa-studies",
            json={"name": f"MSA-{tag}", "part_count": 2, "operator_count": 2,
                  "replicates": 2, "tolerance": 10.0,
                  "data": {"readings": [[[10.0, 10.05], [20.0, 20.05]],
                                        [[10.02, 10.07], [20.02, 20.07]]]}},
        )
        base = f"/api/projects/{self.project.id}/qms"
        self.assertEqual(len(self.client.get(f"{base}/d8").json()["items"]), 1)
        self.assertEqual(self.client.get(f"{base}/d8/{d8}").json()["code"], f"D8-L-{tag}")
        self.assertEqual(len(self.client.get(f"{base}/control-plans").json()["items"]), 1)
        self.assertEqual(len(self.client.get(f"{base}/msa-studies").json()["items"]), 1)
        self.assertEqual(len(self.client.get(f"{base}/fmeas").json()["items"]), 1)
        self.assertEqual(len(self.client.get(f"{base}/suppliers").json()["items"]), 1)
        iqc_items = self.client.get(f"{base}/iqc-records").json()["items"]
        self.assertEqual(len(iqc_items), 1)
        self.assertIsNotNone(iqc_items[0]["scar_id"], "不合格自动生成 SCAR")
        self.assertEqual(len(self.client.get(f"{base}/scars").json()["items"]), 1)
        # 详情端点（quality.manage 动作后的只读面）
        ncr_id = self.client.post(
            f"{base}/ncr-capa",
            json={"code": f"NCR-L-{tag}", "title": "详情"},
        ).json()["id"]
        detail = self.client.get(f"{base}/ncr-capa/{ncr_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["stage"], "draft")
        self.assertEqual(detail.json()["actions"][0]["phase"], "draft")


if __name__ == "__main__":
    unittest.main()
