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

    def test_subscriber_reconnects_and_resubscribes_after_connection_error(self):
        import asyncio

        class FlakyPubSub:
            def __init__(self):
                self.subscriptions = 0
                self.delivered = False

            async def psubscribe(self, *channels):
                self.subscriptions += 1

            async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
                # 真实 pubsub.get_message 会挂起让出事件循环，伪对象同样须挂起，
                # 否则订阅循环自旋饿死 stop_event
                await asyncio.sleep(0.005)
                if self.subscriptions == 1:
                    raise ConnectionError("redis restarted")
                if not self.delivered:
                    self.delivered = True
                    return {"data": b'{"run_id":"r2","type":"done"}'}
                return None

            def aclose(self):
                return None

        class ReconnectingRedis:
            def __init__(self):
                self.pubsub_instance = FlakyPubSub()

            def pubsub(self):
                return self.pubsub_instance

        class CollectingManager:
            def __init__(self):
                self.events = []

            async def broadcast(self, run_id, event):
                self.events.append((run_id, event))

        async def exercise():
            manager = CollectingManager()
            redis_client = ReconnectingRedis()
            subscriber = RedisRunEventSubscriber(
                redis_client,
                manager,
                retry_initial_delay=0.02,
            )
            stop = asyncio.Event()
            task = asyncio.create_task(subscriber.run(stop))
            for _ in range(200):
                await asyncio.sleep(0.01)
                if manager.events:
                    break
            stop.set()
            await asyncio.wait_for(task, timeout=2)
            return manager.events, redis_client.pubsub_instance.subscriptions

        events, subscriptions = asyncio.run(exercise())
        self.assertEqual(events, [("r2", {"run_id": "r2", "type": "done"})])
        self.assertEqual(subscriptions, 2)

    def test_subscriber_stop_event_interrupts_backoff_wait(self):
        import asyncio

        subscriber = RedisRunEventSubscriber(
            None,
            MagicMock(),
            retry_initial_delay=30.0,
        )

        async def exercise():
            stop = asyncio.Event()
            task = asyncio.create_task(subscriber.run(stop))
            await asyncio.sleep(0.05)
            stop.set()
            # 退避等待 30s 期间收到停止事件须立即退出
            await asyncio.wait_for(task, timeout=1)

        asyncio.run(exercise())


if __name__ == "__main__": unittest.main()
