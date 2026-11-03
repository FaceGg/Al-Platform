"""DAG 模型端口字节信封合同测试（Mimosa Medium 21 项收口）。

生产者用 seal_model_port_bytes 打包，消费端 load_model_port 验签解包；
信封存在但内容被篡改/替换必须拒绝。裸载荷（存量工作流）按旧格式放行。
"""
import unittest

import joblib  # noqa: F401  (import guard for the port loader contract)
from sklearn.dummy import DummyClassifier

from app.services.model_artifact_sealing import (
    model_port_is_enveloped,
    seal_model_port_bytes,
    verify_model_port_bytes,
)


class TestModelPortEnvelope(unittest.TestCase):
    def test_roundtrip_preserves_payload_and_reports_sealed(self):
        payload = b"\x80\x04fake-joblib-bytes"
        wire = seal_model_port_bytes(payload)
        self.assertTrue(model_port_is_enveloped(wire))
        inner, sealed = verify_model_port_bytes(wire)
        self.assertTrue(sealed)
        self.assertEqual(inner, payload)

    def test_bare_payload_passes_through_unsealed(self):
        payload = b"\x80\x04legacy-bytes"
        inner, sealed = verify_model_port_bytes(payload)
        self.assertFalse(sealed)
        self.assertEqual(inner, payload)

    def test_tampered_inner_bytes_are_rejected(self):
        payload = b"\x80\x04genuine"
        wire = bytearray(seal_model_port_bytes(payload))
        wire[-1] ^= 0xFF
        with self.assertRaises(ValueError):
            verify_model_port_bytes(bytes(wire))

    def test_forged_header_seal_is_rejected(self):
        payload = b"\x80\x04evil"
        wire = seal_model_port_bytes(payload)
        body = wire[len(b"MLPLATFORM-MODEL-SEAL1\n"):]
        newline = body.index(b"\n")
        import json
        header = json.loads(body[:newline])
        header["model_seal"] = "0" + header["model_seal"][1:]
        forged = (
            wire[: len(b"MLPLATFORM-MODEL-SEAL1\n")]
            + json.dumps(header, sort_keys=True).encode()
            + b"\n"
            + body[newline + 1:]
        )
        with self.assertRaises(ValueError):
            verify_model_port_bytes(bytes(forged))

    def test_corrupt_header_is_rejected(self):
        wire = b"MLPLATFORM-MODEL-SEAL1\nnot-json\npayload"
        with self.assertRaises(ValueError):
            verify_model_port_bytes(wire)

    def test_load_model_port_accepts_enveloped_joblib(self):
        from app.services.model_port import load_model_port

        estimator = DummyClassifier(strategy="most_frequent").fit([[0.0], [1.0]], [0, 1])
        import io
        buffer = io.BytesIO()
        joblib.dump(estimator, buffer)
        wire = seal_model_port_bytes(buffer.getvalue())
        model, pytorch_pkg = load_model_port(wire)
        self.assertIsNone(pytorch_pkg)
        self.assertTrue(hasattr(model, "predict"))

    def test_load_model_port_still_accepts_bare_joblib(self):
        from app.services.model_port import load_model_port

        estimator = DummyClassifier(strategy="most_frequent").fit([[0.0], [1.0]], [0, 1])
        import io
        buffer = io.BytesIO()
        joblib.dump(estimator, buffer)
        model, pytorch_pkg = load_model_port(buffer.getvalue())
        self.assertIsNone(pytorch_pkg)
        self.assertTrue(hasattr(model, "predict"))


if __name__ == "__main__":
    unittest.main()
