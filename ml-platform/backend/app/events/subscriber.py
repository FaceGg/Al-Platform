"""Redis run event subscriber forwarding valid JSON events to WebSockets."""

import asyncio
import json
import logging

logger = logging.getLogger(__name__)

_RETRY_INITIAL_DELAY_SECONDS = 1.0
_RETRY_MAX_DELAY_SECONDS = 30.0
# 连接存活超过该时长后再次断开视为新故障，退避从头计算
_STABLE_CONNECTION_SECONDS = 60.0


class RedisRunEventSubscriber:
    def __init__(
        self,
        redis_client,
        manager,
        channel_prefix="ml-platform:runs",
        retry_initial_delay=_RETRY_INITIAL_DELAY_SECONDS,
        retry_max_delay=_RETRY_MAX_DELAY_SECONDS,
    ):
        self.redis = redis_client
        self.manager = manager
        self.channel_prefix = channel_prefix
        self.retry_initial_delay = retry_initial_delay
        self.retry_max_delay = retry_max_delay

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
        """Consume run events until stopped, reconnecting after Redis outages.

        无自愈时一次 ConnectionError 会让订阅任务静默死亡（main.py 只
        create_task 不察觉）；这里失败后指数退避重连并重新订阅。
        """
        delay = self.retry_initial_delay
        while not stop_event.is_set():
            started_at = asyncio.get_running_loop().time()
            try:
                await self._consume(stop_event)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if stop_event.is_set():
                    return
                uptime = asyncio.get_running_loop().time() - started_at
                if uptime >= _STABLE_CONNECTION_SECONDS:
                    delay = self.retry_initial_delay
                logger.warning(
                    "run event subscriber dropped after %.1fs; "
                    "reconnecting in %.1fs",
                    uptime,
                    delay,
                    exc_info=True,
                )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
            delay = min(delay * 2, self.retry_max_delay)

    async def _consume(self, stop_event: asyncio.Event):
        pubsub = self.redis.pubsub()
        await pubsub.psubscribe(f"{self.channel_prefix}:*")
        try:
            while not stop_event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message:
                    # 单条消息转发失败（如 WS manager 异常）不拖垮订阅
                    try:
                        await self.handle_message(message)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("failed to forward run event")
        finally:
            close = getattr(pubsub, "aclose", None) or getattr(pubsub, "close", None)
            if close:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
