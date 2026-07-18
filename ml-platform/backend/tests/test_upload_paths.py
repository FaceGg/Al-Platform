import os
import unittest

from app.api import datasets, operators


class TestUploadPaths(unittest.TestCase):
    def test_dataset_and_operator_upload_paths_share_container_directory(self):
        self.assertEqual(
            os.path.abspath(datasets.UPLOAD_DIR),
            os.path.abspath(operators.UPLOAD_DIR),
        )


if __name__ == "__main__":
    unittest.main()
