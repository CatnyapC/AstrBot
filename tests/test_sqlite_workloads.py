import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from astrbot.core.utils import sqlite_pool as pool


@pytest.fixture(autouse=True)
def cleanup():
    pool.close_idle()
    yield
    pool.close_idle()


def test_reuses_exclusive_handle_and_closes_old_cursors(tmp_path):
    path = tmp_path / "db"
    lease = pool.connect(path)
    handle = lease._conn
    cursor = lease.execute("CREATE TABLE items(value)")
    lease.execute("INSERT INTO items VALUES (1)")
    lease.close()  # An uncommitted lease cannot leak a write into its successor.
    with pytest.raises(sqlite3.ProgrammingError):
        cursor.fetchone()
    with pool.connect(path) as next_lease:
        assert next_lease._conn is handle
        assert next_lease.execute("SELECT * FROM items").fetchall() == []
        next_lease.execute("INSERT INTO items VALUES (2)")
    with pool.connect(path, persistent=True, workload_name="write") as writer:
        assert writer.execute("SELECT * FROM items").fetchall() == [(2,)]
    with writer:
        writer.execute("INSERT INTO items VALUES (3)")
    writer.close()
    with pool.connect(path) as reader:
        assert reader.execute("SELECT * FROM items").fetchall() == [(2,), (3,)]


def test_saturation_isolated_and_deadline_includes_admission(tmp_path):
    path = tmp_path / "db"
    leases = [pool.connect(path, workload_name="backfill") for _ in range(16)]
    try:
        with pool.connect(path, workload_name="web") as web:
            assert web.execute("SELECT 1").fetchone() == (1,)
        with pytest.raises(sqlite3.OperationalError, match="acquire timeout"):
            pool.connect(path, workload_name="backfill", acquire_timeout=0.01)
        token = pool.DEADLINE.set(0)
        try:
            with pytest.raises(TimeoutError):
                pool.connect(path, workload_name="reply")
        finally:
            pool.DEADLINE.reset(token)
    finally:
        for lease in leases:
            lease.close()


def test_thread_transfer_and_readonly_mode(tmp_path):
    path = tmp_path / "db"
    with pool.connect(path) as conn:
        conn.execute("CREATE TABLE items(value)")
    with ThreadPoolExecutor(2) as workers:

        def use():
            with pool.connect(path) as conn:
                return conn.execute("SELECT 42").fetchone()

        assert all(
            result == (42,) for result in workers.map(lambda _: use(), range(10))
        )
    with pool.connect(path.as_uri() + "?mode=ro", uri=True) as readonly:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            readonly.execute("INSERT INTO items VALUES (1)")


@pytest.mark.asyncio
async def test_scheduler_propagates_workload():
    results = await asyncio.gather(
        *(pool.run(pool.lane, workload_name=name) for name in pool.CONNECTIONS)
    )
    assert results == list(pool.CONNECTIONS)
    assert pool.lane() == "write"


def test_background_scope_keeps_graph_writes_in_writer_lane():
    @pool.scheduled("backfill", sqlite_only=True)
    def read_window():
        assert pool.sqlite_lane() == "backfill"
        assert pool.lane() == "write"

    read_window()
    assert pool.sqlite_lane() == "write"


def test_temporary_objects_and_failed_transactions_do_not_leak(tmp_path):
    path = tmp_path / "db"
    with pool.connect(path) as conn:
        conn.execute("CREATE TABLE items(value)")
        conn.execute("CREATE TEMP TABLE seen(value)")
    with pytest.raises(ValueError):
        with pool.connect(path) as conn:
            assert not conn.execute("SELECT name FROM sqlite_temp_master").fetchall()
            conn.execute("INSERT INTO items VALUES (1)")
            raise ValueError("rollback")
    with pool.connect(path) as conn:
        assert conn.execute("SELECT * FROM items").fetchall() == []
