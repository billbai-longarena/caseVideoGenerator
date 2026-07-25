from __future__ import annotations

from collections import deque
from typing import Optional

from server.app.core.config import Settings


class QueueError(RuntimeError):
    pass


class JobQueue:
    def enqueue(self, job_id: str) -> None:
        raise NotImplementedError

    def dequeue(self, timeout_seconds: int = 5) -> Optional[str]:
        raise NotImplementedError

    def position(self, job_id: str) -> int | None:
        raise NotImplementedError


class InMemoryJobQueue(JobQueue):
    def __init__(self) -> None:
        self._items: deque[str] = deque()

    def enqueue(self, job_id: str) -> None:
        if job_id not in self._items:
            self._items.append(job_id)

    def dequeue(self, timeout_seconds: int = 5) -> Optional[str]:
        if not self._items:
            return None
        return self._items.popleft()

    def position(self, job_id: str) -> int | None:
        for index, item in enumerate(self._items, start=1):
            if item == job_id:
                return index
        return None


class RedisJobQueue(JobQueue):
    key = "case-video:jobs"

    def __init__(self, settings: Settings) -> None:
        try:
            import redis
        except ImportError as exc:
            raise QueueError("redis package is required for RedisJobQueue") from exc
        self.client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    def enqueue(self, job_id: str) -> None:
        queued = self.client.lrange(self.key, 0, -1)
        if job_id not in queued:
            self.client.rpush(self.key, job_id)

    def dequeue(self, timeout_seconds: int = 5) -> Optional[str]:
        item = self.client.blpop(self.key, timeout=timeout_seconds)
        if item is None:
            return None
        return str(item[1])

    def position(self, job_id: str) -> int | None:
        queued = self.client.lrange(self.key, 0, -1)
        for index, item in enumerate(queued, start=1):
            if item == job_id:
                return index
        return None


def build_queue(settings: Settings) -> JobQueue:
    return RedisJobQueue(settings)
