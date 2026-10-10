"""Week 16 storage-binding contract tests: namespace/PVC ownership, controlled
object prefix, read_only injection and the hostPath-always-illegal rule."""

import sys
import unittest

sys.path.insert(0, ".")

from app.services.kubernetes_executor import KubeJobError  # noqa: E402
from app.services.storage_mounts import (  # noqa: E402
    validate_binding,
    build_mount_injection,
)

PROJECT_ID = "1f2e3d4c-5b6a-7988-1122-334455667788"


class TestStorageBindings(unittest.TestCase):
    def test_04_object_prefix_must_be_project_scoped(self):
        ok = validate_binding(
            project_id=PROJECT_ID,
            mode="object_prefix",
            object_prefix=f"projects/{PROJECT_ID}/datasets/run1/",
        )
        self.assertEqual(f"projects/{PROJECT_ID}/datasets/run1/", ok["object_prefix"])
        with self.assertRaises(KubeJobError) as raised:
            validate_binding(project_id=PROJECT_ID, mode="object_prefix", object_prefix="projects/other-project-id/")
        self.assertEqual("STORAGE_BINDING_INVALID", raised.exception.code)
        with self.assertRaises(KubeJobError) as raised:
            validate_binding(project_id=PROJECT_ID, mode="object_prefix", object_prefix="data/escape/../")
        self.assertEqual("STORAGE_BINDING_INVALID", raised.exception.code)

    def test_05_pvc_mode_requires_name_and_read_flag_pairing(self):
        ok = validate_binding(project_id=PROJECT_ID, mode="pvc", pvc_name="w16-data", access="read_only")
        self.assertEqual("w16-data", ok["pvc_name"])
        with self.assertRaises(KubeJobError):
            validate_binding(project_id=PROJECT_ID, mode="pvc", pvc_name=None)
        with self.assertRaises(KubeJobError):
            validate_binding(project_id=PROJECT_ID, mode="object_prefix", object_prefix=None)

    def test_06_hostpath_and_unknown_modes_are_always_illegal(self):
        with self.assertRaises(KubeJobError) as raised:
            validate_binding(project_id=PROJECT_ID, mode="hostPath", extra={"hostPath": "/etc"})
        self.assertEqual("STORAGE_BINDING_INVALID", raised.exception.code)
        with self.assertRaises(KubeJobError):
            validate_binding(project_id=PROJECT_ID, mode="something_else")

    def test_07_read_only_injection_marks_mount_readonly(self):
        binding = validate_binding(project_id=PROJECT_ID, mode="pvc", pvc_name="w16-data", access="read_only")
        injection = build_mount_injection(binding, mount_path="/data")
        self.assertEqual("/data", injection["mount_path"])
        volumes = injection["volumes"]
        self.assertEqual(1, len(volumes))
        self.assertEqual("w16-data", volumes[0]["persistentVolumeClaim"]["claimName"])
        self.assertTrue(volumes[0]["persistentVolumeClaim"]["readOnly"])
        self.assertTrue(injection["volume_mounts"][0]["readOnly"])

        writable = validate_binding(project_id=PROJECT_ID, mode="pvc", pvc_name="w16-data", access="read_write")
        writable_injection = build_mount_injection(writable, mount_path="/data")
        self.assertFalse(writable_injection["volumes"][0]["persistentVolumeClaim"]["readOnly"])

    def test_08_unknown_access_flag_rejected(self):
        with self.assertRaises(KubeJobError):
            validate_binding(project_id=PROJECT_ID, mode="pvc", pvc_name="w16-data", access="read_mostly")


if __name__ == "__main__":
    unittest.main()
