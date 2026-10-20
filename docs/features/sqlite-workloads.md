# SQLite workload scheduling

`astrbot.core.utils.sqlite_pool` owns the process-wide SQLite admission, reusable
connections and blocking worker entry. Router, Dashboard and Thread Archive use
`connect`; asynchronous Dashboard reads use `run`. There is no new dependency.

| Workload | Connection reservation | Blocking workers |
| --- | ---: | ---: |
| Main reply | 24 | 6 |
| Web reads | 16 | 3 |
| Backfill / extraction | 16 | 3 |
| Writes / other operations | 8 | 3 |

The 64-connection allocation matches Neo4j's workload proportions. SQLite caps
apply across database paths in this process, including idle connections. A pool
key also separates path/URI mode, busy timeout and transaction mode. Reservations
are not borrowed. Connections open lazily. Saturation of the backfill reservation
cannot consume web/reply slots. SQLite still permits one writer per database;
more connections do not make writes parallel.

Each lease exclusively owns its connection. Returning a lease closes its cursors,
rolls back uncommitted work and clears row factories, tracing, progress handlers
and query-only state. Read-only URIs remain read-only. Connections with temporary
objects, attachments or custom connection subclasses are closed instead of
reused. File replacement invalidates old idle handles. `:memory:` is not reused.

A short `with connect(...)` commits/rolls back and returns the lease. Existing
long-lived Router/Archive stores explicitly use `persistent=True`: their `with`
blocks retain SQLite's transaction semantics until the store calls `close()`.
Their existing locks and short transaction boundaries remain authoritative.

The shared workload/deadline context also feeds the existing Neo4j recall pools.
Backfill orchestration scopes SQLite alone: it must not relabel graph writes as
backfill recall. Recall's own consumer scope still selects its graph workload.
Worker admission checks existing deadlines before starting queued work; connection
admission uses the earlier of its original acquire timeout and scoped deadline.
No query timeout, permission rule or database policy is relaxed.

Use `uv run pytest -q tests/test_sqlite_workloads.py` from the AstrBot root for
lease, rollback, isolation, concurrency, reservation and context regressions.
