import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.events.redis import RedisRunEventPublisher
from app.events.subscriber import RedisRunEventSubscriber


class FakeRedis:
    def __init__(self): self.calls = []
    def publish(self, channel, message): self.calls.append((channel, message))


class TestEventBridge(unittest.TestCase):
    def test_publisher_uses_json_and_run_channel(self):
        redis = FakeRedis()
        RedisRunEventPublisher(redis).publish("run-1", {"type": "completed", "status": "completed"})
        channel, message = redis.calls[0]
        self.assertEqual(channel, "ml-platform:runs:run-1")
        self.assertEqual(json.loads(message)["run_id"], "run-1")

    def test_publisher_rejects_events_without_type(self):
        with self.assertRaises(ValueError):
            RedisRunEventPublisher(FakeRedis()).publish("run-1", {})

    def test_subscriber_ignores_invalid_and_forwards_valid_json(self):
        class Manager:
            def __init__(self): self.events = []
            async def broadcast(self, run_id, event): self.events.append((run_id, event))
        manager = Manager()
        subscriber = RedisRunEventSubscriber(None, manager)
        import asyncio
        self.assertFalse(asyncio.run(subscriber.handle_message({"data": b"bad"})))
        self.assertTrue(asyncio.run(subscriber.handle_message({"data": b'{"run_id":"r","type":"done"}'})))
        self.assertEqual(manager.events[0][0], "r")

    def test_application_lifecycle_starts_and_stops_redis_subscriber(self):
        import asyncio
        from app import main

        redis_client = MagicMock()
        redis_client.aclose = AsyncMock()
        subscriber = MagicMock()
        subscriber.run = AsyncMock()
        app_settings = SimpleNamespace(
            redis_events_url=SimpleNamespace(
                get_secret_value=lambda: "redis://events/1",
            ),
        )

        async def exercise():
            with patch.object(
                main.redis_async.Redis,
                "from_url",
                return_value=redis_client,
            ), patch.object(
                main,
                "RedisRunEventSubscriber",
                return_value=subscriber,
            ):
                runtime = await main.start_event_subscriber(app_settings)
                await asyncio.sleep(0)
                subscriber.run.assert_awaited_once()
                await main.stop_event_subscriber(runtime)
                redis_client.aclose.assert_awaited_once()

        asyncio.run(exercise())


if __name__ == "__main__": unittest.main()
