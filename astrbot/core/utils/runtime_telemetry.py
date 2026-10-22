"""Bounded, payload-free in-process observations; never a scheduling authority."""

import functools
import inspect
import os
import threading
import time
import uuid
from collections import deque
from contextlib import aclosing, contextmanager, nullcontext
from contextvars import ContextVar

_context = ContextVar("runtime_observation", default={})
_lock = threading.RLock()
_active = {}
_events = deque(maxlen=512)
_sequence = 0
_INSTANCE = uuid.uuid4().hex


def current():
    return dict(_context.get())


def emit(stage, status, *, run="", owner="", **fields):
    global _sequence
    with _lock:
        _sequence += 1
        event = {"seq": _sequence, "ts": time.time(), "stage": stage, "status": status}
        event.update(
            {k: v for k, v in {"run": run, "owner": owner, **fields}.items() if v != ""}
        )
        _events.append(event)


def begin(resource="", *, owner="", stage="", run="", state="running", provider=""):
    context = current()
    observation = {
        "id": uuid.uuid4().hex,
        "owner": owner or context.get("owner", "unknown"),
        "run": run or context.get("run") or uuid.uuid4().hex[:12],
        "stage": stage or context.get("stage", ""),
        "resource": resource,
        "caller_stage": context.get("stage", ""),
        "state": state,
        "started": time.monotonic(),
    }
    if provider:
        observation["provider"] = provider
    with _lock:
        _active[observation["id"]] = observation
    emit(
        observation["stage"],
        state,
        run=observation["run"],
        owner=observation["owner"],
        resource=resource,
    )
    return observation


def transition(observation, state):
    with _lock:
        if observation["id"] in _active:
            observation["state"] = state


def finish(observation, status="done"):
    with _lock:
        if _active.pop(observation["id"], None) is None:
            return
    emit(
        observation["stage"],
        status,
        run=observation["run"],
        owner=observation["owner"],
        resource=observation["resource"],
        elapsed_ms=round((time.monotonic() - observation["started"]) * 1000),
    )


@contextmanager
def span(resource="", *, owner="", stage="", run="", provider=""):
    observation = begin(resource, owner=owner, stage=stage, run=run, provider=provider)
    token = _context.set(observation)
    status = "done"
    try:
        yield observation
    except BaseException as error:
        status = (
            "cancelled"
            if type(error).__name__ in {"CancelledError", "GeneratorExit"}
            else "error"
        )
        raise
    finally:
        _context.reset(token)
        finish(observation, status)


def observe(*, resource="", owner="", stage="", provider=None, run=None):
    """Observe real invocation lifetime, including cancellation and generator close."""

    def decorate(function):
        def scope(args, kwargs):
            if resource == "llm" and current().get("resource") == resource:
                return nullcontext()
            return span(
                resource,
                owner=owner(*args, **kwargs) if callable(owner) else owner,
                stage=stage,
                provider=provider(*args, **kwargs) if provider else "",
                run=run(*args, **kwargs) if run else "",
            )

        if inspect.isasyncgenfunction(function):

            @functools.wraps(function)
            async def call(*args, **kwargs):
                with scope(args, kwargs):
                    async with aclosing(function(*args, **kwargs)) as iterator:
                        async for item in iterator:
                            yield item
        elif inspect.iscoroutinefunction(function):

            @functools.wraps(function)
            async def call(*args, **kwargs):
                with scope(args, kwargs):
                    return await function(*args, **kwargs)
        else:

            @functools.wraps(function)
            def call(*args, **kwargs):
                with scope(args, kwargs):
                    return function(*args, **kwargs)

        return call

    return decorate


def snapshot(after=0):
    now = time.monotonic()
    with _lock:
        return {
            "instance": _INSTANCE,
            "pid": os.getpid(),
            "sampled_at": time.time(),
            "sequence": _sequence,
            "active": [
                {
                    **{k: v for k, v in item.items() if k != "started" and v != ""},
                    "age_ms": round((now - item["started"]) * 1000),
                }
                for item in _active.values()
            ],
            "events": [dict(item) for item in _events if item["seq"] > after],
            "truncated": bool(_events and after and after < _events[0]["seq"] - 1),
        }
