"""pbkdf2_sha256 stdlib 实现合同测试（升级批次 P1，2026-11-03）。

四条固化向量由真实 passlib 1.7.4 产出（迁移前捕获），锁死线上格式兼容性：
旧哈希零迁移可验证；新哈希 600k 轮（OWASP 2023）；畸形哈希抛 ValueError
族（登录路径按失败处理）。登录 rehash 钩子消费 needs_update 完成轮数升级。
"""
import unittest

from app.services.password_hashing import (
    DEFAULT_ROUNDS,
    LEGACY_ROUNDS,
    PasswordHasher,
    pbkdf2_sha256_hash,
    pbkdf2_sha256_needs_update,
    pbkdf2_sha256_verify,
)

# （明文, 真实 passlib 1.7.4 产出的 29000 轮哈希）——兼容性锚点，勿改
_PASSLIB_VECTORS = [
    (
        "admin123",
        "$pbkdf2-sha256$29000$ce597/0fQyhlTOld6z0HwA$t6H44AgObjQ5vUT8NTpYrrGlwY74oEpZVtCjPnqq8H0",
    ),
    (
        "Catarc@1020",
        "$pbkdf2-sha256$29000$.38vRQjhfO89ByDkXAuh9A$QZhciRanX4zBfaLeEGw1Dl2stavRZl92bMauJpQiXBk",
    ),
    (
        "pass-with-ünicode-密码",
        "$pbkdf2-sha256$29000$tZaytnYOAWBsTal1DoHwPg$Xsdgc4lW29XJyQ4GBJg6nmb2P/IBQib5U4fp8XTnzjg",
    ),
    (
        "a" * 100,
        "$pbkdf2-sha256$29000$IWTMWYuR0jrnPMeYM0bIGQ$Zoipbecuq8sUK8iI41mGPAtYkdf4zLPdYI7PdQT9Hbc",
    ),
]


class TestPasslibCompatibility(unittest.TestCase):
    def test_real_passlib_hashes_verify_without_migration(self):
        for password, stored in _PASSLIB_VECTORS:
            with self.subTest(password=password[:10]):
                self.assertTrue(pbkdf2_sha256_verify(password, stored))
                self.assertFalse(pbkdf2_sha256_verify("wrong-password", stored))

    def test_legacy_rounds_flag_needs_update(self):
        # 29000 轮旧哈希：可验证 + 标记升级；600k 新哈希：无需升级
        _, legacy = _PASSLIB_VECTORS[0]
        self.assertTrue(pbkdf2_sha256_needs_update(legacy))
        fresh = pbkdf2_sha256_hash("x")
        self.assertFalse(pbkdf2_sha256_needs_update(fresh))

    def test_new_hash_uses_owasp_rounds_and_same_format(self):
        stored = pbkdf2_sha256_hash("roundtrip")
        self.assertTrue(stored.startswith(f"$pbkdf2-sha256${DEFAULT_ROUNDS}$"))
        self.assertTrue(pbkdf2_sha256_verify("roundtrip", stored))
        self.assertGreater(DEFAULT_ROUNDS, LEGACY_ROUNDS * 10)


class TestHasherFacade(unittest.TestCase):
    """四个调用点（auth/main/annotator_identity/inference_api_keys）的门面合同。"""

    def setUp(self):
        self.hasher = PasswordHasher()

    def test_facade_matches_passlib_style_api(self):
        stored = self.hasher.hash("secret-pw")
        self.assertTrue(self.hasher.verify("secret-pw", stored))
        self.assertFalse(self.hasher.verify("other", stored))
        self.assertIsInstance(self.hasher.needs_update(stored), bool)

    def test_malformed_hashes_raise_value_error_family(self):
        for bad in ("garbage", "", "$pbkdf2-sha256$abc$salt$hash", None, 12345):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.hasher.verify("pw", bad)
                with self.assertRaises(ValueError):
                    self.hasher.needs_update(bad)

    def test_injected_salt_and_rounds_are_deterministic(self):
        first = pbkdf2_sha256_hash("pw", rounds=LEGACY_ROUNDS, salt=b"0123456789abcdef")
        second = pbkdf2_sha256_hash("pw", rounds=LEGACY_ROUNDS, salt=b"0123456789abcdef")
        self.assertEqual(first, second)
        self.assertTrue(pbkdf2_sha256_verify("pw", first))


if __name__ == "__main__":
    unittest.main()
