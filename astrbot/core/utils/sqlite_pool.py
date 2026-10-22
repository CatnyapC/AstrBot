"""Process-wide SQLite leases and worker queues, reserved by workload."""

import asyncio
import atexit
import functools
import sqlite3
import time
import weakref
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from pathlib import Path
from threading import Condition
from urllib.parse import unquote, urlsplit

from . import runtime_telemetry as telemetry

CONNECTIONS = {"reply": 24, "web": 16, "backfill": 16, "write": 8}
LANE = ContextVar("database_workload", default="write")
_SQLITE_LANE = ContextVar("sqlite_workload", default=None)
DEADLINE = ContextVar("database_deadline", default=None)
_condition = Condition()
_active = defaultdict(int)
_idle = defaultdict(list)
_executors = {}


def lane():
    return LANE.get()


def sqlite_lane():
    return _SQLITE_LANE.get() or lane()


def deadline(value=None):
    scoped = DEADLINE.get()
    return scoped if value is None else value if scoped is None else min(value, scoped)


@contextmanager
def workload(name, *, sqlite_only=False):
    if name not in CONNECTIONS:
        raise ValueError("database_workload_invalid")
    variable = _SQLITE_LANE if sqlite_only else LANE
    token = variable.set(name)
    try:
        yield
    finally:
        variable.reset(token)


def scheduled(name, *, sqlite_only=False):
    """Scope synchronous or asynchronous callers without losing their signatures."""

    def decorate(function):
        if asyncio.iscoroutinefunction(function):

            @functools.wraps(function)
            async def call(*args, **kwargs):
                with workload(name, sqlite_only=sqlite_only):
                    return await function(*args, **kwargs)
        else:

            @functools.wraps(function)
            def call(*args, **kwargs):
                with workload(name, sqlite_only=sqlite_only):
                    return function(*args, **kwargs)

        return call

    return decorate


async def run(function, *args, workload_name="web", **kwargs):
    with workload(workload_name):
        with _condition:
            executor = _executors.setdefault(workload_name, None)
            if executor is None:
                executor = _executors[workload_name] = ThreadPoolExecutor(
                    max_workers={"reply": 6, "web": 3, "backfill": 3, "write": 3}[
                        workload_name
                    ],
                    thread_name_prefix=f"sqlite-{workload_name}",
                )

        def execute():
            expires = deadline()
            if expires is not None and time.perf_counter() >= expires:
                raise TimeoutError("sqlite_workload_deadline")
            return function(*args, **kwargs)

        return await asyncio.get_running_loop().run_in_executor(
            executor, copy_context().run, execute
        )


def _identity(database, uri):
    raw = str(database)
    path = Path(unquote(urlsplit(raw).path) if uri and raw.startswith("file:") else raw)
    if raw == ":memory:" or (uri and "mode=memory" in raw):
        return None
    try:
        stat = path.stat()
        return stat.st_dev, stat.st_ino
    except OSError:
        return None


class Connection:
    """One exclusive lease; close cursors and roll back before returning it."""

    def __init__(self, conn, key, identity, reusable, persistent, observation):
        self._observation = observation
        self._conn = conn
        self._persistent = persistent
        self._key = key
        self._identity = identity
        self._reusable = reusable
        self._cursors = weakref.WeakSet()

    def __getattr__(self, name):
        if self._conn is None:
            raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
        return getattr(self._conn, name)

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value

    def cursor(self, *args, **kwargs):
        cursor = self.__getattr__("cursor")(*args, **kwargs)
        self._cursors.add(cursor)
        return cursor

    def execute(self, *args):
        cursor = self.__getattr__("execute")(*args)
        self._cursors.add(cursor)
        return cursor

    def executemany(self, *args):
        cursor = self.__getattr__("executemany")(*args)
        self._cursors.add(cursor)
        return cursor

    def executescript(self, *args):
        cursor = self.__getattr__("executescript")(*args)
        self._cursors.add(cursor)
        return cursor

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None:
                self.commit()
            else:
                self.rollback()
        finally:
            if not self._persistent:
                self.close()

    def __del__(self):
        self.close()

    def close(self):
        conn = self._conn
        if conn is None:
            return
        self._conn = None
        try:
            reusable = self._reusable and type(conn) is sqlite3.Connection
            try:
                for cursor in self._cursors:
                    cursor.close()
                conn.rollback()
                # Temporary tables and attached databases belong to the original lease.
                if (
                    conn.execute("SELECT 1 FROM sqlite_temp_master LIMIT 1").fetchone()
                    or len(conn.execute("PRAGMA database_list").fetchall()) > 2
                ):
                    reusable = False
                conn.row_factory = None
                conn.text_factory = str
                conn.set_trace_callback(None)
                conn.set_progress_handler(None, 0)
                conn.execute("PRAGMA query_only=OFF")
                conn.execute(f"PRAGMA busy_timeout={int(self._key[3] * 1000)}")
            except sqlite3.Error:
                reusable = False
            with _condition:
                _active[self._key[0]] -= 1
                if reusable:
                    _idle[self._key].append((conn, self._identity))
                else:
                    conn.close()
                _condition.notify_all()
        finally:
            telemetry.finish(self._observation)


def connect(
    database,
    timeout=5.0,
    *,
    uri=False,
    check_same_thread=False,
    isolation_level="",
    workload_name=None,
    acquire_timeout=10.0,
    persistent=False,
):
    # Connections are exclusively leased; transfer between worker threads is safe.
    name = workload_name or sqlite_lane()
    if name not in CONNECTIONS:
        raise ValueError("database_workload_invalid")
    observation = telemetry.begin("sqlite", stage="connection", state="waiting")
    try:
        return _acquire(
            database,
            timeout,
            uri=uri,
            check_same_thread=check_same_thread,
            isolation_level=isolation_level,
            workload_name=name,
            acquire_timeout=acquire_timeout,
            persistent=persistent,
            observation=observation,
        )
    except BaseException:
        telemetry.finish(observation, "error")
        raise


def _acquire(
    database,
    timeout,
    *,
    uri,
    check_same_thread,
    isolation_level,
    workload_name,
    acquire_timeout,
    persistent,
    observation,
):
    name = workload_name
    raw = str(database)
    key = (name, raw, uri, float(timeout), isolation_level)
    expires = deadline(time.perf_counter() + acquire_timeout)
    with _condition:
        while _active[name] >= CONNECTIONS[name]:
            remaining = expires - time.perf_counter()
            if remaining <= 0:
                raise sqlite3.OperationalError(
                    "sqlite workload connection acquire timeout"
                )
            _condition.wait(remaining)
        if time.perf_counter() >= expires:
            raise TimeoutError("sqlite_workload_deadline")
        _active[name] += 1
        identity = _identity(raw, uri)
        candidates = _idle[key]
        conn = None
        while candidates:
            candidate, previous = candidates.pop()
            if identity == previous:
                conn = candidate
                break
            candidate.close()
        # Bound open handles across all databases, including idle handles.
        idle_keys = [k for k, entries in _idle.items() if k[0] == name and entries]
        while sum(len(_idle[k]) for k in idle_keys) + _active[name] > CONNECTIONS[name]:
            evict = next(k for k in idle_keys if _idle[k])
            _idle[evict].pop()[0].close()
    try:
        if conn is None:
            conn = sqlite3.connect(
                raw,
                timeout=timeout,
                uri=uri,
                check_same_thread=False,
                isolation_level=isolation_level,
            )
        telemetry.transition(observation, "leased")
        return Connection(
            conn,
            key,
            _identity(raw, uri),
            raw != ":memory:" and "mode=memory" not in raw,
            persistent,
            observation,
        )
    except BaseException:
        with _condition:
            _active[name] -= 1
            _condition.notify_all()
        raise


def close_idle():
    with _condition:
        for entries in _idle.values():
            while entries:
                entries.pop()[0].close()
        _idle.clear()


atexit.register(close_idle)


def runtime_pool_snapshot():
    """Public aggregate pool capacity; no database paths or SQL."""
    with _condition:
        return {
            "capacity": sum(CONNECTIONS.values()),
            "active": sum(_active.values()),
            "idle": sum(map(len, _idle.values())),
            "lanes": dict(CONNECTIONS),
        }
