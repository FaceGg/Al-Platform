"""M6 半监督精调档 1 验收证据回归（技术方案 §6.4 判据② / §6.2 验收）。

tools/acceptance/run_m6_precision_at_k.py 的快速回归切片：小规模确定性夹具
（秒级跑完，不写库、不写仓库产物），断言三件事：

1. 标签阈值重标定后 **precision@k（k=报警预算）提升**、阈值方向正确
   （抬高）、误报类报警率下降——本夹具上三项均成立（见各用例注释）；
2. **合成基准重跑仍全过门禁**：synthetic_auc ≥ 0.85、
   normal_fpr ≤ contamination×1.5、stability ≥ 0.8；
3. 产物字典含显式 ``mode`` 与 §6.2 门槛状态——合成标签下**真实门槛必须
   报 not_unlocked**（平台真实 confirmed_fault 标签为 0）。

说明：门禁判定同时保留平台 ``evaluate_anomaly_gates`` 原样输出与按真实
normal_fpr 的复算值（平台实现把 normal_fpr=0.0 读成 1.0，属既有缺陷，
本任务不改该文件）——用例断言复算值，并要求两者的差异必须留痕。
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = BACKEND_ROOT / "tools" / "acceptance" / "run_m6_precision_at_k.py"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class _LokySingleCore:
    """测试窗口内把 loky 的 CPU 上限压到 1。

    Windows 上 sklearn KMeans（§6.2 形态聚类必经）首次调用会经 loky 查询
    物理核数——一次 PowerShell 子进程（本机约 3.5 秒）。限为 1 可跳过该查询
    且**不改变计算结果**（仅影响并行度）；退出即恢复环境变量，不影响同进程
    内其它测试模块。
    """

    def __enter__(self):
        self._previous = os.environ.get("LOKY_MAX_CPU_COUNT")
        os.environ["LOKY_MAX_CPU_COUNT"] = "1"
        return self

    def __exit__(self, *exc_info):
        if self._previous is None:
            os.environ.pop("LOKY_MAX_CPU_COUNT", None)
        else:
            os.environ["LOKY_MAX_CPU_COUNT"] = self._previous
        return False


def _load_acceptance_script():
    spec = importlib.util.spec_from_file_location("run_m6_precision_at_k", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


acceptance_script = _load_acceptance_script()


class TestM6PrecisionAtKAcceptance(unittest.TestCase):
    """§6.4 判据②的机制验证（合成标签）回归切片。"""

    @classmethod
    def setUpClass(cls):
        # 小规模确定性夹具：iforest(30 树) + 500 行正常 + 50 确认故障
        # + 15 误报 + 60 正常背景；confirmed=50 恰好压 §6.2 的 ≥50 门槛。
        with _LokySingleCore():
            cls.result = acceptance_script.run_acceptance(
                family_id="iforest",
                model_params={"n_estimators": 30, "max_samples": 128},
                contamination=0.01,
                seed=42,
                train_rows=500,
                confirmed_count=50,
                false_alarm_count=15,
                normal_count=60,
                n_features=6,
                compute_stability=True,
            )

    def test_precision_at_k_improves_after_recalibration(self):
        """判据②之一：precision@k 提升 + 阈值方向 + 误报率下降。

        本夹具上三项均成立：真故障分数整体高于误报样本（现场前提），
        因此标签重标定把阈值抬到误报带之上 → 处置批次内真故障占比上升。
        """
        precision = self.result["precision_at_k"]
        before = precision["before"]
        after = precision["after"]
        self.assertIsNotNone(before["precision"])
        self.assertIsNotNone(after["precision"])
        self.assertGreater(after["precision"], before["precision"])
        self.assertTrue(precision["improved"])
        # 阈值方向：重标定阈值高于一期基线阈值（误报带被压到阈值之下）
        self.assertGreater(after["threshold"], before["threshold"])
        self.assertGreater(
            self.result["thresholds"]["recalibrated_score"],
            self.result["thresholds"]["baseline_score"],
        )

    def test_false_alarm_alarm_rate_drops_and_distribution_shifts_down(self):
        """判据②之三：false_alarm 报警率下降、分数裕度分布整体下移。"""
        detection = self.result["detection"]
        self.assertLess(
            detection["false_alarm_alarm_rate_on_false_alarm_class"]["after"],
            detection["false_alarm_alarm_rate_on_false_alarm_class"]["before"],
        )
        self.assertLessEqual(
            detection["normal_background_alarm_rate"]["after"],
            detection["normal_background_alarm_rate"]["before"],
        )
        shift = self.result["false_alarm_shift"]
        self.assertTrue(shift["shifted_down"])
        # 档 1 只动阈值：误报样本分数本身不变，「分数 − 阈值」裕度整体下移 Δt
        self.assertAlmostEqual(
            shift["false_alarm_score_margin_median_shift"],
            -shift["threshold_delta"],
            places=6,
        )

    def test_synthetic_benchmark_gates_still_pass_after_recalibration(self):
        """判据②之二：合成基准重跑仍全过门禁（防精调过拟合确认样本）。"""
        recalibrated = self.result["synthetic_benchmark"]["recalibrated"]
        contamination = self.result["contamination"]
        self.assertGreaterEqual(recalibrated["synthetic_auc"], 0.85)
        self.assertLessEqual(recalibrated["normal_fpr"], contamination * 1.5)
        self.assertGreaterEqual(recalibrated["stability"], 0.8)
        self.assertTrue(recalibrated["gates_passed_corrected"])
        # 平台原样输出与复算值若有差异，必须留痕（平台 falsy-zero 缺陷）
        if not recalibrated["gates_passed"]:
            self.assertIsNotNone(recalibrated["platform_gate_defect"])
        self.assertTrue(self.result["verdict"]["synthetic_benchmark_gates_still_pass"])

    def test_artifact_reports_mode_and_m6_gate_status(self):
        """产物必须含显式 mode 与 §6.2 门槛状态；合成标签下真实门槛不解锁。"""
        self.assertIn("mode", self.result)
        self.assertEqual(self.result["mode"], "mechanism-verification")
        real_gate = self.result["m6_real_gate"]
        self.assertFalse(real_gate["unlocked"])
        self.assertEqual(real_gate["status"], "not_unlocked")
        self.assertEqual(real_gate["confirmed_count"], 0)
        mechanism_gate = self.result["m6_mechanism_gate"]
        self.assertTrue(mechanism_gate["unlocked"])
        self.assertEqual(mechanism_gate["confirmed_count"], 50)
        self.assertGreaterEqual(mechanism_gate["morphology_cluster_count"], 2)
        verdict = self.result["verdict"]
        self.assertFalse(verdict["criterion_2_release_ready"])
        self.assertTrue(verdict["release_blockers"])

    def test_markdown_report_numbers_match_json(self):
        """Markdown 报告与 JSON 同源：关键数字必须逐字出现。"""
        markdown = acceptance_script.render_markdown(self.result)
        self.assertIn(str(self.result["thresholds"]["baseline_score"]), markdown)
        self.assertIn(str(self.result["thresholds"]["recalibrated_score"]), markdown)
        self.assertIn(str(self.result["precision_at_k"]["before"]["precision"]), markdown)
        self.assertIn(str(self.result["precision_at_k"]["after"]["precision"]), markdown)
        self.assertIn(self.result["mode"], markdown)
        self.assertIn("not_unlocked", markdown)

    def test_cli_writes_json_and_markdown_artifacts(self):
        """CLI 端到端：--output / --markdown 落盘且内容与返回值一致。"""
        with tempfile.TemporaryDirectory(prefix="m6-precision-at-k-") as directory:
            json_path = Path(directory) / "artifact.json"
            md_path = Path(directory) / "artifact.md"
            argv = [
                "run_m6_precision_at_k.py",
                "--output", str(json_path),
                "--markdown", str(md_path),
                "--train-rows", "500",
                "--confirmed", "50",
                "--false-alarm", "15",
                "--normal", "60",
                "--skip-stability",
            ]
            original_argv = sys.argv
            try:
                sys.argv = argv
                with _LokySingleCore():
                    exit_code = acceptance_script.main()
            finally:
                sys.argv = original_argv
            self.assertEqual(exit_code, 0)
            self.assertTrue(json_path.is_file())
            self.assertTrue(md_path.is_file())
            import json

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["mode"], "mechanism-verification")
            self.assertIn("precision_at_k", payload)
            self.assertIn("m6_real_gate", payload)
            self.assertIn(
                str(payload["thresholds"]["recalibrated_score"]),
                md_path.read_text(encoding="utf-8"),
            )


class TestConsoleEncodingGuard(unittest.TestCase):
    """Windows 控制台代码页回归（2026-11-14 CI Quality (windows-latest) 失败根因）。

    症状：``run_m6_precision_at_k.py`` 用 ``print(json.dumps(..., ensure_ascii=False))``
    输出中文结论；Windows 的管道 stdout 默认用 locale 代码页（CI runner 为
    ``cp1252``）→ ``UnicodeEncodeError: 'charmap' codec can't encode characters``
    → 整个模块 FAILED（同提交 Ubuntu 全绿）。修复见 ``app/console_encoding.py``。

    本类把「非 UTF-8 stdout」显式化（``PYTHONIOENCODING=cp1252``），使回归在
    任何宿主 locale 下都可复现，不再依赖 CI 的 Windows runner。
    """

    def test_cli_survives_non_utf8_stdout_encoding(self):
        """stdout 为 cp1252 时 CLI 必须正常退出（不得抛 UnicodeEncodeError）。"""
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "cp1252"
        env["PYTHONPATH"] = str(BACKEND_ROOT)
        env["LOKY_MAX_CPU_COUNT"] = "1"
        with tempfile.TemporaryDirectory(prefix="m6-cp1252-") as directory:
            json_path = Path(directory) / "artifact.json"
            md_path = Path(directory) / "artifact.md"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--output",
                    str(json_path),
                    "--markdown",
                    str(md_path),
                    "--train-rows",
                    "300",
                    "--confirmed",
                    "50",
                    "--false-alarm",
                    "15",
                    "--normal",
                    "60",
                    "--skip-stability",
                ],
                capture_output=True,
                cwd=str(BACKEND_ROOT),
                env=env,
                timeout=900,
            )
            combined = completed.stdout.decode("utf-8", "replace") + completed.stderr.decode(
                "utf-8", "replace"
            )
            self.assertNotIn("UnicodeEncodeError", combined)
            self.assertEqual(completed.returncode, 0, combined[-2000:])
            self.assertTrue(json_path.is_file())
            self.assertTrue(md_path.is_file())

    def test_force_utf8_stdio_reconfigures_to_utf8(self):
        """守卫必须把流切到 UTF-8 且对不可编码字符退化为 replace。"""
        from app.console_encoding import force_utf8_stdio

        recorded: list[dict] = []

        class _Fake:
            def reconfigure(self, **kwargs):
                recorded.append(kwargs)

        original_out, original_err = sys.stdout, sys.stderr
        try:
            sys.stdout = _Fake()
            sys.stderr = _Fake()
            force_utf8_stdio()
        finally:
            sys.stdout, sys.stderr = original_out, original_err
        self.assertTrue(recorded)
        for kwargs in recorded:
            self.assertEqual(kwargs.get("encoding"), "utf-8")
            self.assertEqual(kwargs.get("errors"), "replace")

    def test_force_utf8_stdio_never_raises_on_unreconfigurable_stream(self):
        """流已关闭/被替换成非 TextIOWrapper 时守卫必须静默跳过，不得抛异常。"""
        from app.console_encoding import force_utf8_stdio

        class _Boom:
            def reconfigure(self, **kwargs):
                raise ValueError("I/O operation on closed file")

        class _NoReconfigure:
            pass

        original_out, original_err = sys.stdout, sys.stderr
        try:
            sys.stdout = _Boom()
            sys.stderr = _NoReconfigure()
            force_utf8_stdio()
        finally:
            sys.stdout, sys.stderr = original_out, original_err


if __name__ == "__main__":
    unittest.main()
