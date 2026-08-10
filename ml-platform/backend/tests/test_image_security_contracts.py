import json
import re
import unittest
from pathlib import Path


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
BASE_RECORD = ROOT / "docs" / "security" / "python-base-image.json"
REQUIREMENTS = BACKEND / "requirements.txt"
EXCEPTION = ROOT / "docs" / "security" / "cryptography-pkcs7-mlflow-exception.json"


class ImageSecurityContractTests(unittest.TestCase):
    def test_all_production_python_images_use_one_immutable_reference(self):
        record = json.loads(BASE_RECORD.read_text(encoding="utf-8"))
        reference = record["reference"]
        self.assertRegex(reference, r"^[^@]+@sha256:[0-9a-f]{64}$")
        for path in DOCKERFILES:
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(first_line, f"FROM {reference}", path.name)

    def test_direct_security_dependencies_are_fixed(self):
        lines = {
            line.split("#", 1)[0].strip().casefold()
            for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        self.assertIn("cryptography==50.0.*", lines)
        self.assertIn("jaraco.context==6.1.0", lines)
        self.assertIn("wheel==0.46.2", lines)

    def test_cryptography_exception_is_removed_after_clean_resolution(self):
        self.assertFalse(EXCEPTION.exists())


if __name__ == "__main__":
    unittest.main()
