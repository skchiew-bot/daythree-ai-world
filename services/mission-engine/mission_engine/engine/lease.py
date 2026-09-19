"""Per-task execution lease (R0, ADR-013 F5).

The task queue is a plain Redis list with no ack, so a task can reach two workers (a
restarted worker used to requeue every `running` task globally). Without a lease the
second worker re-runs a task another worker is mid-call on, and the provider bills both.

A worker may execute a task only while it holds `daythree:task_lease:<task_id>`:
- acquired with SET NX PX (only one holder at a time);
- refreshed every `LEASE_REFRESH_SECONDS` while the work runs, so a long model call keeps it;
- released at the end, and only if the token is still ours;
- never released by a crashed worker, so it simply expires after `LEASE_TTL_MS` and the
  orphan sweep in `worker.main` can requeue the task. Recovery delay is therefore bounded
  by the TTL plus the sweep interval (about 30 seconds), well inside the 60 second target.

Refresh and release compare the stored token before acting, using WATCH/MULTI rather than a
Lua script, so they also work against fakeredis without a Lua runtime.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Coroutine
from typing import Any, TypeVar

import structlog
from redis.asyncio import Redis
from redis.exceptions import WatchError

from contracts.ids import EntityId

logger = structlog.get_logger(__name__)

LEASE_KEY_PREFIX = "daythree:task_lease:"
LEASE_TTL_MS = 20_000
LEASE_REFRESH_SECONDS = 5.0
# The worker's shared Redis client has socket_timeout=None (BRPOP needs it, see
# `worker.deps.build_redis_client`), so a half-open connection would hang a refresh forever.
LEASE_REFRESH_TIMEOUT_SECONDS = 2.0

T = TypeVar("T")


class LeaseLostError(Exception):
    """The lease expired or was taken over while the work was running; the work was cancelled."""


def lease_key(task_id: EntityId) -> str:
    return f"{LEASE_KEY_PREFIX}{task_id}"


async def is_leased(redis_client: Redis, task_id: EntityId) -> bool:
    return bool(await redis_client.exists(lease_key(task_id)))


class TaskLease:
    def __init__(
        self,
        redis_client: Redis,
        task_id: EntityId,
        *,
        ttl_ms: int = LEASE_TTL_MS,
        refresh_seconds: float = LEASE_REFRESH_SECONDS,
    ):
        self._redis = redis_client
        self._key = lease_key(task_id)
        self._token = uuid.uuid4().hex
        self._ttl_ms = ttl_ms
        self._refresh_seconds = refresh_seconds
        self.refresh_timeout_seconds = LEASE_REFRESH_TIMEOUT_SECONDS

    async def acquire(self) -> bool:
        return bool(await self._redis.set(self._key, self._token, nx=True, px=self._ttl_ms))

    async def refresh(self) -> bool:
        """Extends the lease if it is still ours. False means it was lost."""
        return await self._if_ours(lambda pipe: pipe.pexpire(self._key, self._ttl_ms))

    async def release(self) -> None:
        await self._if_ours(lambda pipe: pipe.delete(self._key))

    async def run(self, work: Coroutine[Any, Any, T]) -> T:
        """Runs `work` while refreshing the lease. If the lease is lost, cancels the work
        and raises `LeaseLostError`: another worker may now own the task."""
        runner = asyncio.ensure_future(work)
        heartbeat = asyncio.ensure_future(self._heartbeat())
        try:
            await asyncio.wait({runner, heartbeat}, return_when=asyncio.FIRST_COMPLETED)
            if runner.done():
                return runner.result()
        finally:
            # Also runs when this coroutine itself is cancelled: never leave the work
            # running (and possibly billing) after the lease has been given up.
            heartbeat.cancel()
            runner.cancel()  # no-op if it already finished
            await asyncio.gather(heartbeat, runner, return_exceptions=True)
        raise LeaseLostError(f"Lease {self._key} was lost while the task was running.")

    async def _heartbeat(self) -> None:
        """Returns (ending the race in `run`) once the lease is lost: refresh reports the
        token gone, or refreshes keep failing to the point that the NEXT check could land
        after the key has expired (a hung or failing Redis connection means we can no longer
        prove we hold it, and another worker may soon).

        Residual window, not closable here: a process that is paused after a provider request
        was already sent (SIGSTOP, a VM freeze) can outlive its lease and finish a call
        another worker also makes. Closing that needs provider-side fencing (idempotency
        keys), which the OpenAI and Anthropic APIs do not offer for completions."""
        last_ok = time.monotonic()
        ttl = self._ttl_ms / 1000
        # One heartbeat cycle is at most a refresh interval plus the refresh timeout.
        worst_cycle = self._refresh_seconds + self.refresh_timeout_seconds
        while True:
            await asyncio.sleep(self._refresh_seconds)
            try:
                refreshed = await asyncio.wait_for(self.refresh(), timeout=self.refresh_timeout_seconds)
            except Exception:  # noqa: BLE001 - includes timeouts; a Redis blip must not kill the work by itself
                logger.exception("task_lease_refresh_failed", key=self._key)
                refreshed = None
            if refreshed is False:
                return
            if refreshed:
                last_ok = time.monotonic()
            elif time.monotonic() - last_ok + worst_cycle >= ttl:
                logger.error("task_lease_unrefreshable_before_expiry", key=self._key)
                return

    async def _if_ours(self, command) -> bool:
        async with self._redis.pipeline(transaction=True) as pipe:
            try:
                await pipe.watch(self._key)
                current = await pipe.get(self._key)
                if isinstance(current, bytes):  # the worker's client does not decode responses
                    current = current.decode()
                if current != self._token:
                    return False
                pipe.multi()
                command(pipe)
                await pipe.execute()
                return True
            except WatchError:
                return False
