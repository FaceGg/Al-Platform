"""Redis run event publisher."""

import json


class RedisRunEventPublisher:
    def __init__(self, client, channel_prefix: str = "ml-platform:runs"):
        self.client = client
        self.channel_prefix = channel_prefix

    def publish(self, run_id: str, payload: dict) -> None:
        event = {**payload, "run_id": run_id}
        if "type" not in event:
            raise ValueError("Run event type is required")
        self.client.publish(
            f"{self.channel_prefix}:{run_id}",
            json.dumps(event, ensure_ascii=True),
        )

    def close(self) -> None:
        self.client.close()
