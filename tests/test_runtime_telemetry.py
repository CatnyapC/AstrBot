import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from astrbot.core.utils import runtime_telemetry as telemetry
from astrbot.core.utils import sqlite_pool


def test_sqlite_lease_ownership_and_release(tmp_path):
    with telemetry.span(owner="memory", stage="worker", run="anonymous"):
        with ThreadPoolExecutor(1) as pool:
            connection = pool.submit(
                copy_context().run, sqlite_pool.connect, tmp_path / "test.db"
            ).result()
        leases = [
            item
            for item in telemetry.snapshot()["active"]
            if item.get("resource") == "sqlite"
        ]
        assert leases[-1]["owner"] == "memory"
        assert leases[-1]["state"] == "leased"
        connection.close()
        connection.close()
        assert not any(
            item.get("resource") == "sqlite" for item in telemetry.snapshot()["active"]
        )


@pytest.mark.asyncio
async def test_cancellation_releases_observation():
    entered = asyncio.Event()

    @telemetry.observe(resource="jev", owner="reply", stage="perception")
    async def request():
        entered.set()
        await asyncio.Future()

    task = asyncio.create_task(request())
    await entered.wait()
    assert any(item.get("resource") == "jev" for item in telemetry.snapshot()["active"])
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    state = telemetry.snapshot()
    assert not any(item.get("resource") == "jev" for item in state["active"])
    assert state["events"][-1]["status"] == "cancelled"


def test_wait_failure_and_event_buffer(tmp_path, monkeypatch):
    monkeypatch.setitem(sqlite_pool.CONNECTIONS, "write", 0)
    with pytest.raises(Exception):
        sqlite_pool.connect(tmp_path / "test.db", acquire_timeout=0)
    assert not any(
        item.get("resource") == "sqlite" for item in telemetry.snapshot()["active"]
    )
    for _ in range(520):
        telemetry.emit("perception", "done")
    state = telemetry.snapshot(1)
    assert len(state["events"]) == 512
    assert state["truncated"]


@pytest.mark.asyncio
async def test_stream_close_releases_nested_observations():
    closed = []

    @telemetry.observe(resource="llm", owner="reply", stage="composer")
    async def response():
        try:
            yield "chunk"
            yield "done"
        finally:
            closed.append(True)

    iterator = response()
    assert await anext(iterator) == "chunk"
    await iterator.aclose()
    assert closed == [True]
    assert not any(
        item.get("resource") == "llm" for item in telemetry.snapshot()["active"]
    )
