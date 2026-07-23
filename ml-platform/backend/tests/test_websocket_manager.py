"""Tests for app.websocket.manager.ConnectionManager.

The manager had only indirect coverage via run-reliability tests. We
exercise connect/disconnect/broadcast with fake WebSocket objects.
"""
import asyncio
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, ".")

from app.websocket.manager import ConnectionManager


def _fake_ws():
    """Create a fake WebSocket that records sent JSON messages."""
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.accept = AsyncMock()
    return ws


class TestConnectionManagerConnect(unittest.TestCase):
    def test_connect_accepts_and_registers(self):
        manager = ConnectionManager()
        ws = _fake_ws()
        asyncio.run(manager.connect("run-1", ws))
        ws.accept.assert_awaited_once()
        self.assertIn("run-1", manager._connections)
        self.assertIn(ws, manager._connections["run-1"])

    def test_connect_multiple_websockets_same_run(self):
        manager = ConnectionManager()
        ws1, ws2 = _fake_ws(), _fake_ws()
        asyncio.run(manager.connect("run-1", ws1))
        asyncio.run(manager.connect("run-1", ws2))
        self.assertEqual(len(manager._connections["run-1"]), 2)


class TestConnectionManagerDisconnect(unittest.TestCase):
    def test_disconnect_removes_websocket(self):
        manager = ConnectionManager()
        ws = _fake_ws()
        asyncio.run(manager.connect("run-1", ws))
        manager.disconnect("run-1", ws)
        self.assertNotIn("run-1", manager._connections)

    def test_disconnect_unknown_websocket_is_noop(self):
        manager = ConnectionManager()
        ws = _fake_ws()
        # Disconnecting something never connected should not raise.
        manager.disconnect("run-1", ws)

    def test_disconnect_when_run_not_registered_is_noop(self):
        manager = ConnectionManager()
        manager.disconnect("missing-run", _fake_ws())

    def test_disconnect_keeps_run_when_other_connections_remain(self):
        manager = ConnectionManager()
        ws1, ws2 = _fake_ws(), _fake_ws()
        asyncio.run(manager.connect("run-1", ws1))
        asyncio.run(manager.connect("run-1", ws2))
        manager.disconnect("run-1", ws1)
        self.assertIn("run-1", manager._connections)
        self.assertEqual(manager._connections["run-1"], [ws2])


class TestConnectionManagerBroadcast(unittest.TestCase):
    def test_broadcast_sends_to_all_connections(self):
        manager = ConnectionManager()
        ws1, ws2 = _fake_ws(), _fake_ws()
        asyncio.run(manager.connect("run-1", ws1))
        asyncio.run(manager.connect("run-1", ws2))
        message = {"type": "node_status", "status": "running"}
        asyncio.run(manager.broadcast("run-1", message))
        ws1.send_json.assert_awaited_once_with(message)
        ws2.send_json.assert_awaited_once_with(message)

    def test_broadcast_unknown_run_is_noop(self):
        manager = ConnectionManager()
        # Should not raise even though no connections exist.
        asyncio.run(manager.broadcast("missing-run", {"type": "x"}))

    def test_broadcast_removes_failed_connections(self):
        manager = ConnectionManager()
        good = _fake_ws()
        bad = _fake_ws()
        bad.send_json = AsyncMock(side_effect=RuntimeError("disconnected"))
        asyncio.run(manager.connect("run-1", good))
        asyncio.run(manager.connect("run-1", bad))
        asyncio.run(manager.broadcast("run-1", {"type": "x"}))
        good.send_json.assert_awaited_once()
        # The bad connection should have been pruned; the good one stays, so
        # the run key remains in the registry with only the good websocket.
        self.assertIn("run-1", manager._connections)
        self.assertEqual(manager._connections["run-1"], [good])
        self.assertNotIn(bad, manager._connections["run-1"])


if __name__ == "__main__":
    unittest.main()
