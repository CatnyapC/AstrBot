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


@pytest.mark.asyncio
async def test_stream_can_close_in_another_task_without_leaking_context():
    closed = []

    @telemetry.observe(resource="llm", owner="reply", stage="composer")
    async def response():
        try:
            yield telemetry.current()["id"]
        finally:
            closed.append(telemetry.current()["id"])

    iterator = response()
    observation_id = await anext(iterator)
    await asyncio.create_task(iterator.aclose())
    assert closed == [observation_id]
    assert telemetry.current() == {}
    assert not any(
        item["id"] == observation_id for item in telemetry.snapshot()["active"]
    )


@pytest.mark.asyncio
async def test_stream_restores_each_consumers_context_and_keeps_one_observation():
    @telemetry.observe(resource="llm", owner="reply", stage="composer")
    async def response():
        yield telemetry.current()["id"]
        yield telemetry.current()["id"]

    iterator = response()
    try:
        with telemetry.span(owner="memory", run="first-consumer") as first:
            observation_id = await anext(iterator)
            assert telemetry.current()["id"] == first["id"]
        with telemetry.span(owner="reference", run="second-consumer") as second:
            assert await asyncio.create_task(anext(iterator)) == observation_id
            assert telemetry.current()["id"] == second["id"]
            with pytest.raises(StopAsyncIteration):
                await asyncio.create_task(anext(iterator))
        assert telemetry.current() == {}
    finally:
        await iterator.aclose()


@pytest.mark.asyncio
async def test_abandoned_stream_finalizer_releases_observation_without_task_error():
    import gc

    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    errors = []
    closed = asyncio.Event()
    loop.set_exception_handler(lambda loop, context: errors.append(context))

    @telemetry.observe(resource="llm", owner="reply", stage="composer")
    async def response():
        try:
            yield telemetry.current()["id"]
        finally:
            closed.set()

    try:
        iterator = response()
        observation_id = await anext(iterator)
        del iterator
        gc.collect()
        await asyncio.wait_for(closed.wait(), 1)
        await asyncio.sleep(0)
        assert errors == []
        assert telemetry.current() == {}
        assert not any(
            item["id"] == observation_id for item in telemetry.snapshot()["active"]
        )
    finally:
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_nested_stream_wrappers_share_lease_when_closed_from_another_task():
    @telemetry.observe(resource="llm")
    async def provider():
        yield telemetry.current()["id"]

    @telemetry.observe(resource="llm", owner="reply", stage="composer")
    async def response():
        async for item in provider():
            yield item

    iterator = response()
    observation_id = await anext(iterator)
    leases = [
        item for item in telemetry.snapshot()["active"] if item.get("resource") == "llm"
    ]
    assert [item["id"] for item in leases] == [observation_id]
    assert telemetry.current() == {}
    await asyncio.create_task(iterator.aclose())
    assert not any(
        item["id"] == observation_id for item in telemetry.snapshot()["active"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_stream_failure_and_cancellation_restore_context_and_release(cancel):
    entered = asyncio.Event()
    closed = []

    @telemetry.observe(resource="llm", owner="reply", stage="composer")
    async def response():
        try:
            yield telemetry.current()["id"]
            entered.set()
            if cancel:
                await asyncio.Future()
            raise RuntimeError("provider failed")
        finally:
            closed.append(telemetry.current()["id"])

    with telemetry.span(owner="memory", run="caller") as caller:
        iterator = response()
        observation_id = await anext(iterator)
        task = asyncio.create_task(anext(iterator))
        await entered.wait()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await task
        assert telemetry.current()["id"] == caller["id"]
    assert closed == [observation_id]
    assert not any(
        item["id"] == observation_id for item in telemetry.snapshot()["active"]
    )
