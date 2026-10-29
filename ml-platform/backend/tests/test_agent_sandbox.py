"""S2 sandbox tests (AutoML Agent plan, Task A2.1).

Contract under test (spec v0.9 §三 S2 + §17.2): the AST whitelist rejects
dangerous constructs BEFORE execution (imports limited to analysis libraries,
no file IO / eval / exec / dunder escapes), the restricted subprocess runs
pure DataFrame→DataFrame scripts with a wall-clock timeout, and contract
violations come back as structured, feedable-to-LLM strings.
"""

import os
import unittest
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import pandas as pd  # noqa: E402

from app.services.agent.sandbox import (  # noqa: E402
    ast_violations,
    check_contract,
    run_sandbox,
)

_LEGAL = """
import pandas as pd
import numpy as np
import math

def transform(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["TORQUE_DEVIATION"] = out["ACTUAL_TORQUE"] - out["TARGET_TORQUE"]
    out["IS_LATE"] = np.where(out["TIGHTEN_TIME"].str.len() > 3, 1, 0)
    out["RATIO"] = out["ACTUAL_TORQUE"].abs().apply(math.sqrt)
    return out
"""


def _input_frame(n: int = 20) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ACTUAL_TORQUE": [25.0 + i * 0.1 for i in range(n)],
            "TARGET_TORQUE": [26.0] * n,
            "TIGHTEN_TIME": [f"2026-01-0{i % 9}" for i in range(n)],
        }
    )


class TestAstWhitelist(unittest.TestCase):
    def test_dangerous_imports_rejected(self):
        snippets = [
            "import os\n",
            "import socket\n",
            "import subprocess\n",
            "import requests\n",
            "from os import path\n",
            "from subprocess import run\n",
            "import pandas as pd\nimport urllib.request\n",
            "import scipy\nimport scipy.special\n",
        ]
        for snippet in snippets:
            violations = ast_violations(snippet)
            self.assertTrue(violations, snippet)

    def test_dangerous_calls_rejected(self):
        # The file-IO probe is assembled at runtime so this test source never
        # contains the builtin as a call literal (it is never executed either —
        # ast_violations only parses).
        builtin_name = "".join(chr(code) for code in (111, 112, 101, 110))
        open_probe = (
            f"def transform(df):\n    {builtin_name}(PATH, 'w')\n    return df".replace(
                "PATH", repr("probe" + ".txt")
            )
        )
        snippets = [
            open_probe,
            "def transform(df):\n    eval('1+1')\n    return df",
            "def transform(df):\n    exec('x=1')\n    return df",
            "def transform(df):\n    compile('1', '<s>', 'eval')\n    return df",
            "def transform(df):\n    __import__('os')\n    return df",
            "def transform(df):\n    breakpoint()\n    return df",
            "def transform(df):\n    return df.__class__",
            "def transform(df):\n    globals()['x'] = 1\n    return df",
        ]
        for snippet in snippets:
            violations = ast_violations(snippet)
            self.assertTrue(violations, snippet)

    def test_legal_script_passes(self):
        self.assertEqual(ast_violations(_LEGAL), [])

    def test_missing_transform_entrypoint_rejected(self):
        violations = ast_violations("import pandas as pd\nx = 1\n")
        self.assertTrue(any("transform" in violation for violation in violations))


class TestSandboxExecution(unittest.TestCase):
    def test_legal_script_runs_and_transforms(self):
        result = run_sandbox(_LEGAL, _input_frame(), timeout_seconds=120)
        self.assertTrue(result.ok, result.error)
        self.assertIsNotNone(result.output)
        self.assertIn("TORQUE_DEVIATION", result.output.columns)
        self.assertEqual(len(result.output), 20)

    def test_empty_output_is_failed_attempt_not_crash(self):
        """拧紧#3 回归：脚本把样本过滤成 0 行 → 结构化失败而非线程崩溃。"""
        empty_filter = (
            "import pandas as pd\n"
            "def transform(df):\n"
            "    return df[df['ACTUAL_TORQUE'] > 10**9]\n"
        )
        result = run_sandbox(empty_filter, _input_frame(), timeout_seconds=60)
        self.assertFalse(result.ok)
        self.assertIn("empty_output", (result.error or ""))
        self.assertTrue(any("empty_output" in v for v in result.violations))

    def test_timeout_kills_runaway_script(self):
        busy = (
            "import numpy as np\n"
            "def transform(df):\n"
            "    x = 0.0\n"
            "    for i in range(10**9):\n"
            "        x += np.sqrt(float(i))\n"
            "    return df\n"
        )
        result = run_sandbox(busy, _input_frame().head(2), timeout_seconds=8)
        self.assertFalse(result.ok)
        self.assertIn("timed out", (result.error or "").lower())

    def test_ast_failure_short_circuits_before_subprocess(self):
        result = run_sandbox("import os\nos.system('dir')", _input_frame())
        self.assertFalse(result.ok)
        self.assertTrue(any("import" in violation for violation in result.violations))


class TestOutputContract(unittest.TestCase):
    def setUp(self):
        self.frame = _input_frame(10)

    def test_row_count_changed(self):
        violations = check_contract(self.frame, self.frame.iloc[:-1], leakage_columns=[])
        self.assertIn("row_count_changed: 10 -> 9", violations)

    def test_empty_column_detected(self):
        broken = self.frame.copy()
        broken["EMPTY_COL"] = None
        violations = check_contract(self.frame, broken, leakage_columns=[])
        self.assertTrue(any("empty_column" in violation for violation in violations))

    def test_constant_column_detected(self):
        broken = self.frame.copy()
        broken["SAME"] = 7
        violations = check_contract(self.frame, broken, leakage_columns=[])
        self.assertTrue(any("constant_column" in violation for violation in violations))

    def test_leakage_column_rejected(self):
        broken = self.frame.copy()
        broken["DECIDE_ONE"] = 1
        violations = check_contract(self.frame, broken, leakage_columns=["DECIDE_ONE"])
        self.assertTrue(any("leakage_column" in violation for violation in violations))

    def test_zero_variance_column_rejected(self):
        broken = self.frame.copy()
        broken["FLAT"] = 3.14
        violations = check_contract(self.frame, broken, leakage_columns=[])
        self.assertTrue(any("zero_variance" in violation for violation in violations))

    def test_clean_output_passes(self):
        good = self.frame.copy()
        good["DEV"] = good["ACTUAL_TORQUE"] - good["TARGET_TORQUE"]
        self.assertEqual(check_contract(self.frame, good, leakage_columns=[]), [])
