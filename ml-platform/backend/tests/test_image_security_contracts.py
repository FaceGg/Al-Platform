import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.security_scans import _pip_audit_report_error


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "ml-platform" / "backend"
DOCKERFILES = tuple(
    BACKEND / name
    for name in (
        "Dockerfile",
        "Dockerfile.worker",
        "Dockerfile.inference",
        "Dockerfile.tensorboard",
    )
)
BASE_RECORD = ROOT / ".github" / "contracts" / "python-base-image.json"
REQUIREMENTS = BACKEND / "requirements.txt"
EXCEPTION = ROOT / ".github" / "contracts" / "cryptography-pkcs7-mlflow-exception.json"
COMPOSE = ROOT / "docker-compose.yml"


class ImageSecurityContractTests(unittest.TestCase):
    def test_all_production_python_images_use_one_immutable_reference(self):
        record = json.loads(BASE_RECORD.read_text(encoding="utf-8"))
        reference = record["reference"]
        self.assertRegex(reference, r"^[^@]+@sha256:[0-9a-f]{64}$")
        for path in DOCKERFILES:
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(first_line, f"FROM {reference}", path.name)

    def test_wolfi_images_install_recorded_python_and_keep_non_root_runtime(self):
        record = json.loads(BASE_RECORD.read_text(encoding="utf-8"))
        runtime = record["runtime"]
        python_package = runtime["python_package"]
        pip_package = runtime["pip_package"]
        non_root_uid = runtime["non_root_uid"]
        self.assertEqual(non_root_uid, 1000)
        for path in DOCKERFILES:
            content = path.read_text(encoding="utf-8")
            self.assertIn("apk add --no-cache", content, path.name)
            self.assertIn(python_package, content, path.name)
            self.assertIn(pip_package, content, path.name)
            self.assertRegex(
                content,
                r"addgroup\s+-S\s+-g\s+1000\s+app\s+&&\s+adduser.*-u\s+1000.*-G\s+app\s+app",
                path.name,
            )
            self.assertIn("ENV HOME=/home/app", content, path.name)
            self.assertIn(f"USER {non_root_uid}:{non_root_uid}", content, path.name)
            self.assertIn(
                "python3.11 -m pip install --retries 10 --resume-retries 20 --timeout 120 "
                "-r requirements.txt",
                content,
                path.name,
            )

    def test_runtime_record_uses_current_wolfi_python_311_security_pins(self):
        record = json.loads(BASE_RECORD.read_text(encoding="utf-8"))
        runtime = record["runtime"]
        self.assertEqual(runtime["python_package"], "python-3.11=3.11.16-r1")
        self.assertEqual(runtime["pip_package"], "py3.11-pip=26.2.1-r0")

    def test_wolfi_runtime_install_retries_transient_apk_download_failures(self):
        runtime = json.loads(BASE_RECORD.read_text(encoding="utf-8"))["runtime"]
        install_command = (
            f"apk add --no-cache {runtime['python_package']} {runtime['pip_package']}"
        )
        expected_retry = (
            "for attempt in 1 2 3; do\n"
            f"        if {install_command}; then\n"
            "            exit 0;\n"
            "        fi;\n"
            "        if [ \"$attempt\" -eq 3 ]; then\n"
            "            exit 1;\n"
            "        fi;\n"
            "        sleep \"$attempt\";\n"
            "    done"
        )
        for path in DOCKERFILES:
            content = path.read_text(encoding="utf-8").replace(" \\\n", "\n")
            self.assertIn(expected_retry, content, path.name)

    def test_backend_host_mounts_keep_the_established_numeric_identity(self):
        compose = COMPOSE.read_text(encoding="utf-8")
        backend = DOCKERFILES[0].read_text(encoding="utf-8")
        self.assertIn("./ml-platform/backend/data:/app/data", compose)
        self.assertIn("./ml-platform/backend/uploads:/app/app/uploads", compose)
        self.assertIn("chown -R app:app /home/app data app/uploads /tmp/ml-platform", backend)
        self.assertIn("USER 1000:1000", backend)

    def test_direct_security_dependencies_are_fixed(self):
        lines = {
            line.split("#", 1)[0].strip().casefold()
            for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        self.assertIn("cryptography==50.0.*", lines)
        self.assertIn("jaraco.context==6.1.0", lines)
        self.assertIn("wheel==0.46.2", lines)

    def test_tensorboard_supports_the_patched_setuptools_release(self):
        lines = {
            line.split("#", 1)[0].strip().casefold()
            for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        self.assertIn("tensorboard==2.21.*", lines)
        self.assertIn("setuptools==83.0.0", lines)

    def test_cryptography_exception_is_removed_after_clean_resolution(self):
        self.assertFalse(EXCEPTION.exists())

    def test_generated_pip_audit_report_requires_all_clean_controlled_packages(self):
        dependencies = [
            {"name": "cryptography", "version": "50.0.0", "vulns": []},
            {"name": "jaraco-context", "version": "6.1.0", "vulns": []},
            {"name": "wheel", "version": "0.46.2", "vulns": []},
        ]
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "pip-audit.json"
            report_path.write_text(
                json.dumps({"dependencies": dependencies}), encoding="utf-8"
            )
            self.assertIsNone(_pip_audit_report_error(report_path))

            report_path.write_text(
                json.dumps({"dependencies": dependencies[:-1]}), encoding="utf-8"
            )
            self.assertEqual(
                _pip_audit_report_error(report_path),
                "PIP_AUDIT_REQUIRED_PACKAGE_MISSING",
            )

            dependencies[0]["vulns"] = [{"id": "TEST-VULNERABILITY"}]
            report_path.write_text(
                json.dumps({"dependencies": dependencies}), encoding="utf-8"
            )
            self.assertEqual(
                _pip_audit_report_error(report_path),
                "PIP_AUDIT_VULNERABILITIES_FOUND",
            )


if __name__ == "__main__":
    unittest.main()
