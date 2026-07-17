"""Redis run event subscriber forwarding valid JSON events to WebSockets."""

import asyncio
import json


class RedisRunEventSubscriber:
    def __init__(self, redis_client, manager, channel_prefix="ml-platform:runs"):
        self.redis = redis_client
        self.manager = manager
        self.channel_prefix = channel_prefix

    async def handle_message(self, message: dict) -> bool:
        raw = message.get("data") if isinstance(message, dict) else None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            event = json.loads(raw)
        except (TypeError, ValueError):
            return False
        run_id = event.get("run_id")
        if not run_id or not event.get("type"):
            return False
        await self.manager.broadcast(run_id, event)
        return True

    async def run(self, stop_event: asyncio.Event):
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe(f"{self.channel_prefix}:*")
        try:
            while not stop_event.is_set():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    await self.handle_message(message)
        finally:
            close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if close:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
