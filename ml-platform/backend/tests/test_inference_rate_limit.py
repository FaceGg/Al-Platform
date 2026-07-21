import unittest

from app.services.inference_rate_limit import (
    RateLimitBackendUnavailable,
    RedisTokenBucket,
)


class FakeRedis:
    def __init__(self, result=1, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def eval(self, script, numkeys, *args):
        self.calls.append((script, numkeys, args))
        if self.error:
            raise self.error
        return self.result


class TestInferenceRateLimit(unittest.TestCase):
    def test_consume_returns_bounded_decision_and_namespaced_key(self):
        redis = FakeRedis(result=[1, 4, 0])
        bucket = RedisTokenBucket(redis)
        decision = bucket.consume(
            "deployment:abc:key:def",
            capacity=5,
            refill_per_second=1,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.remaining, 4)
        self.assertEqual(decision.retry_after_seconds, 0)
        self.assertTrue(redis.calls)
        self.assertEqual(redis.calls[0][1], 1)
        self.assertEqual(redis.calls[0][2][0], "deployment:abc:key:def")

    def test_denied_decision_returns_retry_after(self):
        redis = FakeRedis(result=[0, 0, 2])
        decision = RedisTokenBucket(redis).consume(
            "deployment:abc:key:def", capacity=1, refill_per_second=1,
        )
        self.assertFalse(decision.allowed)
        self.assertGreaterEqual(decision.retry_after_seconds, 1)

    def test_backend_failure_is_fail_closed_with_stable_error(self):
        bucket = RedisTokenBucket(FakeRedis(error=ConnectionError("redis down")))
        with self.assertRaisesRegex(
            RateLimitBackendUnavailable,
            "RATE_LIMIT_BACKEND_UNAVAILABLE",
        ):
            bucket.consume("deployment:abc:key:def", capacity=5, refill_per_second=1)


if __name__ == "__main__":
    unittest.main()
