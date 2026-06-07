"""
tests/test_event_bus.py
=======================
Tests for CoordinatorEventBus.
Uses asyncio.run() for async tests — no pytest-asyncio dependency required.
"""

import asyncio
import sys
import os
import time

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from coordinator.event_bus import CoordinatorEventBus, get_event_bus


# ── Helpers ────────────────────────────────────────────────────────────

def run(coro):
    """Run a coroutine in a fresh event loop."""
    return asyncio.run(coro)


# ── Tests ──────────────────────────────────────────────────────────────

def test_publish_adds_to_history():
    """publish() should append exactly one event to history."""
    async def _inner():
        bus = CoordinatorEventBus()
        await bus.publish("node_joined", {"node_id": "abc123", "shard_index": 0})
        h = bus.get_history()
        assert len(h) == 1
        assert h[0]["type"] == "node_joined"
        assert h[0]["data"]["node_id"] == "abc123"

    run(_inner())


def test_get_history_returns_list():
    """get_history() should return a plain list."""
    async def _inner():
        bus = CoordinatorEventBus()
        await bus.publish("node_left", {"node_id": "x1"})
        result = bus.get_history()
        assert isinstance(result, list)
        assert len(result) == 1

    run(_inner())


def test_history_size_cap():
    """history_size cap must not be exceeded."""
    async def _inner():
        bus = CoordinatorEventBus(history_size=3)
        for i in range(5):
            await bus.publish("node_joined", {"node_id": f"n{i}"})
        h = bus.get_history()
        assert len(h) == 3
        # Should contain the last 3 events
        node_ids = [e["data"]["node_id"] for e in h]
        assert node_ids == ["n2", "n3", "n4"]

    run(_inner())


def test_publish_sync_no_exception_without_loop():
    """publish_sync() must not raise even when no asyncio loop is running."""
    bus = CoordinatorEventBus()
    # Called from a plain synchronous context — no loop active.
    bus.publish_sync("node_left", {"node_id": "sync_test"})
    h = bus.get_history()
    assert len(h) == 1
    assert h[0]["type"] == "node_left"


def test_multiple_events_in_order():
    """Events must appear in insertion order in history."""
    async def _inner():
        bus = CoordinatorEventBus()
        types = ["node_joined", "shard_available", "inference_started", "inference_done", "node_left"]
        for t in types:
            await bus.publish(t, {})
        h = bus.get_history()
        assert [e["type"] for e in h] == types

    run(_inner())


def test_event_has_timestamp():
    """Every published event must include a numeric 'ts' field."""
    async def _inner():
        bus = CoordinatorEventBus()
        before = time.time()
        await bus.publish("shard_unavailable", {"shard_index": 2})
        after = time.time()
        h = bus.get_history()
        assert "ts" in h[0]
        assert before <= h[0]["ts"] <= after

    run(_inner())


def test_get_event_bus_singleton():
    """get_event_bus() must return the same singleton instance each time."""
    bus1 = get_event_bus()
    bus2 = get_event_bus()
    assert bus1 is bus2


def test_publish_with_no_subscribers_is_safe():
    """publish() must not raise when there are no subscribers."""
    async def _inner():
        bus = CoordinatorEventBus()
        # Should complete without error
        await bus.publish("inference_started", {"session_id": "s001"})
        assert len(bus.get_history()) == 1

    run(_inner())


def test_publish_sync_adds_to_history_in_async_context():
    """publish_sync() called from within an async context still saves to history."""
    async def _inner():
        bus = CoordinatorEventBus()
        bus.publish_sync("node_joined", {"node_id": "sync_in_async"})
        # Give any scheduled coroutine a chance to run
        await asyncio.sleep(0)
        h = bus.get_history()
        assert len(h) == 1
        assert h[0]["data"]["node_id"] == "sync_in_async"

    run(_inner())
