"""Fail-closed Redis token bucket for inference requests."""

from dataclasses import dataclass
import math


TOKEN_BUCKET_SCRIPT = """
local time = redis.call('TIME')
local now = tonumber(time[1]) + (tonumber(time[2]) / 1000000)
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated_at')
local tokens = tonumber(values[1]) or capacity
local updated_at = tonumber(values[2]) or now
local elapsed = math.max(0, now - updated_at)
tokens = math.min(capacity, tokens + (elapsed * refill))
local allowed = 0
local retry_after = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after = math.max(1, math.ceil((1 - tokens) / refill))
end
local ttl = math.max(1, math.ceil(capacity / refill) + 1)
redis.call('HMSET', KEYS[1], 'tokens', tokens, 'updated_at', now)
redis.call('EXPIRE', KEYS[1], ttl)
return {allowed, math.floor(tokens), retry_after}
"""


class RateLimitBackendUnavailable(RuntimeError):
    def __init__(self, code: str = "RATE_LIMIT_BACKEND_UNAVAILABLE"):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RedisTokenBucket:
    def __init__(self, redis_client):
        self.redis = redis_client

    def consume(self, key, *, capacity, refill_per_second) -> RateLimitDecision:
        if not isinstance(key, str) or not key:
            raise ValueError("rate-limit key must be non-empty")
        if isinstance(capacity, bool) or int(capacity) != capacity or int(capacity) < 1:
            raise ValueError("rate-limit capacity must be a positive integer")
        refill = float(refill_per_second)
        if not math.isfinite(refill) or refill <= 0:
            raise ValueError("rate-limit refill must be positive and finite")
        try:
            result = self.redis.eval(
                TOKEN_BUCKET_SCRIPT,
                1,
                key,
                int(capacity),
                refill,
            )
            allowed, remaining, retry_after = result
            allowed = bool(int(allowed))
            remaining = max(0, min(int(capacity), int(remaining)))
            retry_after = max(0, int(retry_after))
            if not allowed:
                retry_after = max(1, retry_after)
            return RateLimitDecision(allowed, remaining, retry_after)
        except Exception as error:
            raise RateLimitBackendUnavailable() from error
