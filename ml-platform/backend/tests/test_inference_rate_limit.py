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
        self.assertIn("deployment:abc:key:def", redis.calls[0][2])

    def test_backend_failure_is_fail_closed_with_stable_error(self):
        bucket = RedisTokenBucket(FakeRedis(error=ConnectionError("redis down")))
        with self.assertRaisesRegex(
            RateLimitBackendUnavailable,
            "RATE_LIMIT_BACKEND_UNAVAILABLE",
        ):
            bucket.consume("deployment:abc:key:def", capacity=5, refill_per_second=1)


if __name__ == "__main__":
    unittest.main()
