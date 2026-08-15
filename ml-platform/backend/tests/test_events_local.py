"""Tests for app.events.local and app.events.base publishers.

LocalRunEventPublisher and NullRunEventPublisher had no direct tests.
"""
import sys
import unittest

sys.path.insert(0, ".")

from app.events.base import NullRunEventPublisher, RunEventPublisher
from app.events.local import LocalRunEventPublisher


class TestLocalRunEventPublisher(unittest.TestCase):
    def test_publish_invokes_callback_with_arguments(self):
        captured = []

        def callback(run_id, payload):
            captured.append((run_id, payload))

        publisher = LocalRunEventPublisher(callback)
        publisher.publish("run-1", {"type": "node_status", "status": "running"})

        self.assertEqual(len(captured), 1)
        run_id, payload = captured[0]
        self.assertEqual(run_id, "run-1")
        self.assertEqual(payload["type"], "node_status")
        self.assertEqual(payload["status"], "running")

    def test_publish_passes_multiple_events_in_order(self):
        events = []
        publisher = LocalRunEventPublisher(lambda rid, p: events.append((rid, p)))
        publisher.publish("a", {"n": 1})
        publisher.publish("a", {"n": 2})
        publisher.publish("b", {"n": 3})
        self.assertEqual([p for _, p in events], [{"n": 1}, {"n": 2}, {"n": 3}])
        self.assertEqual([r for r, _ in events], ["a", "a", "b"])

    def test_publish_callback_exception_propagates(self):
        def bad_callback(run_id, payload):
            raise ValueError("boom")

        publisher = LocalRunEventPublisher(bad_callback)
        with self.assertRaises(ValueError):
            publisher.publish("run", {})


class TestNullRunEventPublisher(unittest.TestCase):
    def test_publish_returns_none_without_error(self):
        publisher = NullRunEventPublisher()
        result = publisher.publish("run-1", {"type": "run_completed"})
        self.assertIsNone(result)

    def test_publish_handles_empty_payload(self):
        publisher = NullRunEventPublisher()
        publisher.publish("run-1", {})  # should not raise


class TestRunEventPublisherProtocol(unittest.TestCase):
    """Both publishers should satisfy the RunEventPublisher protocol (duck typing)."""

    def test_local_publisher_has_publish(self):
        publisher = LocalRunEventPublisher(lambda r, p: None)
        self.assertTrue(hasattr(publisher, "publish"))
        self.assertTrue(callable(publisher.publish))

    def test_null_publisher_has_publish(self):
        publisher = NullRunEventPublisher()
        self.assertTrue(hasattr(publisher, "publish"))
        self.assertTrue(callable(publisher.publish))

    def test_protocol_accepts_both_instances(self):
        def dispatch(publisher: RunEventPublisher, run_id: str, payload: dict):
            publisher.publish(run_id, payload)

        local = LocalRunEventPublisher(lambda r, p: None)
        null = NullRunEventPublisher()
        # Should not raise for either implementation.
        dispatch(local, "run", {"type": "x"})
        dispatch(null, "run", {"type": "x"})


if __name__ == "__main__":
    unittest.main()
