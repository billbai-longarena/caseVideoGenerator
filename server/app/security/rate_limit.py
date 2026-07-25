from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from fastapi import Request

from server.app.core.config import Settings
from server.app.core.errors import AppError


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter(Protocol):
    def check(self, key: str) -> RateLimitDecision: ...


class InMemoryRateLimiter:
    """Process-local sliding-window limiter used for tests and small installs."""

    def __init__(
        self,
        requests_per_minute: int,
        burst: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = max(1, requests_per_minute) + max(0, burst)
        self.clock = clock
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> RateLimitDecision:
        now = self.clock()
        cutoff = now - 60.0
        with self._lock:
            bucket = self._requests[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, math.ceil(60.0 - (now - bucket[0])))
                return RateLimitDecision(False, self.limit, 0, retry_after)
            bucket.append(now)
            return RateLimitDecision(True, self.limit, self.limit - len(bucket), 0)


class RedisRateLimiter:
    """Shared fixed-window limiter for horizontally scaled API replicas."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        if client is None:
            try:
                import redis
            except ImportError as exc:  # pragma: no cover - deployment smoke covers this
                raise RuntimeError("redis package is required for RedisRateLimiter") from exc
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.client = client
        self.namespace = settings.redis_namespace
        self.limit = max(1, settings.api_rate_limit_per_minute) + max(
            0, settings.api_rate_limit_burst
        )

    def check(self, key: str) -> RateLimitDecision:
        window = int(time.time() // 60)
        redis_key = f"{self.namespace}:rate:{window}:{key}"
        pipeline = self.client.pipeline(transaction=True)
        pipeline.incr(redis_key)
        pipeline.expire(redis_key, 75)
        count, _ = pipeline.execute()
        count = int(count)
        retry_after = max(1, 60 - int(time.time()) % 60)
        return RateLimitDecision(
            allowed=count <= self.limit,
            limit=self.limit,
            remaining=max(0, self.limit - count),
            retry_after_seconds=0 if count <= self.limit else retry_after,
        )


def build_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.rate_limit_backend == "redis":
        return RedisRateLimiter(settings)
    if settings.rate_limit_backend != "memory":
        raise RuntimeError(f"unsupported rate-limit backend: {settings.rate_limit_backend}")
    return InMemoryRateLimiter(
        settings.api_rate_limit_per_minute,
        settings.api_rate_limit_burst,
    )


def enforce_rate_limit(request: Request, limiter: RateLimiter) -> RateLimitDecision | None:
    if request.url.path in {"/health/live", "/health/ready"}:
        return None
    decision = limiter.check(rate_limit_key(request))
    request.state.rate_limit = decision
    if not decision.allowed:
        request.state.rate_limit_retry_after = decision.retry_after_seconds
        raise AppError(
            "rate_limited",
            "request rate limit exceeded",
            public_details={
                "limit": decision.limit,
                "retry_after_seconds": decision.retry_after_seconds,
            },
        )
    return decision


def rate_limit_key(request: Request) -> str:
    tenant = request.headers.get(request.app.state.settings.tenant_header, "").strip()
    authorization = request.headers.get("Authorization", "").strip()
    if authorization:
        identity = hashlib.sha256(authorization.encode("utf-8")).hexdigest()[:24]
        return f"auth:{tenant or '-'}:{identity}"
    client = request.client.host if request.client is not None else "unknown"
    return f"ip:{client}"
