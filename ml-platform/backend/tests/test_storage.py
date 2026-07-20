import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from app.storage.base import StorageError
from app.storage.local import LocalStorage
from app.storage.minio import MinioStorage


class FakeMinioResponse:
    def __init__(self, payload: bytes):
        self._stream = io.BytesIO(payload)
        self.closed = False
        self.released = False

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class FakeMinioClient:
    def __init__(self):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.put_calls: list[tuple[str, str, int]] = []
        self.remove_calls: list[tuple[str, str]] = []
        self.fail_after_put = False
        self.last_response: FakeMinioResponse | None = None

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def put_object(
        self,
        bucket: str,
        key: str,
        source,
        length: int,
    ) -> None:
        payload = source.read()
        self.put_calls.append((bucket, key, length))
        self.objects[(bucket, key)] = payload
        if self.fail_after_put:
            raise RuntimeError("simulated upload failure")

    def get_object(self, bucket: str, key: str) -> FakeMinioResponse:
        try:
            payload = self.objects[(bucket, key)]
        except KeyError as error:
            raise RuntimeError("object not found") from error
        self.last_response = FakeMinioResponse(payload)
        return self.last_response

    def stat_object(self, bucket: str, key: str) -> object:
        if (bucket, key) not in self.objects:
            raise RuntimeError("object not found")
        return object()

    def remove_object(self, bucket: str, key: str) -> None:
        self.remove_calls.append((bucket, key))
        self.objects.pop((bucket, key), None)


class TestLocalStorage(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "source.csv"
        self.payload = b"current,force,quality\n8,3,1\n"
        self.source.write_bytes(self.payload)
        self.storage = LocalStorage(self.root / "objects")

    def tearDown(self):
        self.directory.cleanup()

    def test_local_put_rejects_parent_path(self):
        with self.assertRaises(StorageError):
            self.storage.put(
                self.source,
                project_id="p",
                artifact_id="a",
                filename="../x.csv",
            )

    def test_local_round_trip_preserves_hash(self):
        stored = self.storage.put(self.source, "p", "a", "data.csv")

        self.assertTrue(stored.uri.startswith("file://"))
        self.assertEqual(stored.size, len(self.payload))
        self.assertEqual(stored.sha256, hashlib.sha256(self.payload).hexdigest())
        self.assertTrue(self.storage.verify(stored.uri, stored.sha256, stored.size))
        with self.storage.open(stored.uri) as stream:
            self.assertEqual(stream.read(), self.payload)
        with self.storage.materialize(stored.uri) as path:
            self.assertEqual(path.read_bytes(), self.payload)

        self.assertTrue(self.storage.exists(stored.uri))
        self.storage.delete(stored.uri)
        self.assertFalse(self.storage.exists(stored.uri))

    def test_local_rejects_uri_outside_storage_root(self):
        with self.assertRaises(StorageError):
            self.storage.open(self.source.as_uri())


class TestMinioStorage(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / "source.bin"
        self.payload = b"weld-model-data"
        self.source.write_bytes(self.payload)
        self.client = FakeMinioClient()
        self.storage = MinioStorage(
            self.client,
            "artifacts",
            temp_root=self.root / "cache",
        )

    def tearDown(self):
        self.directory.cleanup()

    def test_minio_round_trip_uses_server_generated_key_and_known_length(self):
        stored = self.storage.put(self.source, "project", "artifact", "model.bin")

        expected_key = "projects/project/artifacts/artifact/model.bin"
        self.assertEqual(stored.uri, f"s3://artifacts/{expected_key}")
        self.assertEqual(
            self.client.put_calls,
            [("artifacts", expected_key, len(self.payload))],
        )
        self.assertTrue(self.storage.verify(stored.uri, stored.sha256, stored.size))
        with self.storage.materialize(stored.uri) as path:
            self.assertEqual(path.read_bytes(), self.payload)
            materialized_parent = path.parent
        self.assertFalse(materialized_parent.exists())
        self.assertTrue(self.client.last_response.closed)
        self.assertTrue(self.client.last_response.released)

    def test_minio_failed_upload_removes_partial_object(self):
        self.client.fail_after_put = True

        with self.assertRaises(StorageError):
            self.storage.put(self.source, "project", "artifact", "model.bin")

        self.assertEqual(
            self.client.remove_calls,
            [("artifacts", "projects/project/artifacts/artifact/model.bin")],
        )
        self.assertEqual(self.client.objects, {})

    def test_minio_rejects_parent_path(self):
        with self.assertRaises(StorageError):
            self.storage.put(self.source, "project", "artifact", "../model.bin")

    def test_minio_materialize_preserves_consumer_exceptions(self):
        stored = self.storage.put(self.source, "project", "artifact", "model.bin")

        with self.assertRaisesRegex(ValueError, "consumer failed"):
            with self.storage.materialize(stored.uri):
                raise ValueError("consumer failed")


if __name__ == "__main__":
    unittest.main()
