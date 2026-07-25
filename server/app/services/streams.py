from __future__ import annotations

import json
import hashlib
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, Sequence

from server.app.core.config import Settings
from server.app.persistence.repository import (
    ArtifactBundleRegistration,
    BudgetApprovalRequired,
    LeaseConflict,
    ModelRunRegistration,
    PhaseCRepository,
    RepositoryError,
)
from server.app.services.stage_graph import STAGE_QUEUES


QUEUE_NAMES = ("planning", "media", "render", "qa")
PRIORITIES = ("interactive", "high", "normal", "low")
STAGE_MESSAGE_FIELDS = frozenset(
    {
        "message_version",
        "tenant_id",
        "job_id",
        "stage_run_id",
        "expected_job_version",
        "input_snapshot_hash",
        "priority",
        "enqueued_at",
    }
)
STREAM_METADATA_FIELDS = frozenset({"outbox_event_id"})


class StreamError(RuntimeError):
    pass


class InvalidStageMessage(StreamError):
    pass


class StageExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class LeaseLost(StageExecutionError):
    def __init__(self, message: str = "worker lost its database lease") -> None:
        super().__init__("worker_lease_lost", message, retryable=True)


class StageCanceled(StageExecutionError):
    def __init__(self, message: str = "stage cancellation was requested") -> None:
        super().__init__("canceled", message, retryable=False)


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def queue_for_stage(stage: str) -> str:
    try:
        return STAGE_QUEUES[stage]
    except KeyError as exc:
        raise StreamError(f"stage has no worker queue mapping: {stage}") from exc


def _required_text(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidStageMessage(f"{name} must be a non-empty string")
    if len(value) > 512:
        raise InvalidStageMessage(f"{name} exceeds the maximum length")
    return value


@dataclass(frozen=True)
class StageMessage:
    message_version: int
    tenant_id: str
    job_id: str
    stage_run_id: str
    expected_job_version: int
    input_snapshot_hash: str
    priority: str
    enqueued_at: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, allow_metadata: bool = False) -> "StageMessage":
        allowed = STAGE_MESSAGE_FIELDS | (STREAM_METADATA_FIELDS if allow_metadata else frozenset())
        unexpected = set(payload) - allowed
        if unexpected:
            raise InvalidStageMessage(
                "stage messages may contain identifiers and snapshots only; unexpected fields: "
                + ", ".join(sorted(unexpected))
            )
        missing = STAGE_MESSAGE_FIELDS - set(payload)
        if missing:
            raise InvalidStageMessage(f"stage message missing fields: {', '.join(sorted(missing))}")
        try:
            message_version = int(payload["message_version"])
            expected_job_version = int(payload["expected_job_version"])
        except (TypeError, ValueError) as exc:
            raise InvalidStageMessage("message_version and expected_job_version must be integers") from exc
        if message_version != 1:
            raise InvalidStageMessage(f"unsupported stage message version: {message_version}")
        if expected_job_version < 1:
            raise InvalidStageMessage("expected_job_version must be positive")
        priority = _required_text(payload, "priority")
        if priority not in PRIORITIES:
            raise InvalidStageMessage(f"unsupported priority: {priority}")
        enqueued_at = _required_text(payload, "enqueued_at")
        try:
            datetime.fromisoformat(enqueued_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidStageMessage("enqueued_at must be ISO-8601") from exc
        return cls(
            message_version=message_version,
            tenant_id=_required_text(payload, "tenant_id"),
            job_id=_required_text(payload, "job_id"),
            stage_run_id=_required_text(payload, "stage_run_id"),
            expected_job_version=expected_job_version,
            input_snapshot_hash=_required_text(payload, "input_snapshot_hash"),
            priority=priority,
            enqueued_at=enqueued_at,
        )

    def as_fields(self) -> dict[str, str]:
        return {
            "message_version": str(self.message_version),
            "tenant_id": self.tenant_id,
            "job_id": self.job_id,
            "stage_run_id": self.stage_run_id,
            "expected_job_version": str(self.expected_job_version),
            "input_snapshot_hash": self.input_snapshot_hash,
            "priority": self.priority,
            "enqueued_at": self.enqueued_at,
        }


@dataclass(frozen=True)
class StreamRecord:
    stream: str
    message_id: str
    fields: dict[str, str]
    deliveries: int = 1

    @property
    def stage_message(self) -> StageMessage:
        return StageMessage.from_mapping(self.fields, allow_metadata=True)


class StreamsBroker(Protocol):
    def publish_stage(
        self,
        queue_name: str,
        message: StageMessage,
        *,
        outbox_event_id: str,
        dead_letter: bool = False,
        dead_letter_fields: Mapping[str, Any] | None = None,
    ) -> str: ...

    def publish_event(
        self,
        topic: str,
        payload: Mapping[str, Any],
        *,
        outbox_event_id: str,
    ) -> str: ...

    def read_stage(
        self,
        queue_name: str,
        *,
        consumer: str,
        count: int = 1,
        block_ms: int = 5_000,
        claim_idle_ms: int | None = None,
    ) -> list[StreamRecord]: ...

    def ack(self, queue_name: str, message_ids: Sequence[str]) -> int: ...

    def pending(self, queue_name: str) -> int: ...

    def quarantine(self, queue_name: str, record: StreamRecord, *, reason: str) -> str: ...


class RedisStreamsBroker:
    """Redis Streams transport with atomic outbox-event deduplication."""

    _PUBLISH_SCRIPT = """
local prior = redis.call('GET', KEYS[1])
if prior then
  return prior
end
local message_id = redis.call('XADD', KEYS[2], '*', unpack(ARGV, 2))
redis.call('SET', KEYS[1], message_id, 'EX', ARGV[1])
return message_id
"""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        if client is None:
            try:
                import redis
            except ImportError as exc:  # pragma: no cover - covered by deployment smoke
                raise StreamError("redis package is required for RedisStreamsBroker") from exc
            client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.client = client
        self.namespace = settings.redis_namespace
        self.group = settings.worker_consumer_group
        self.dedupe_ttl_seconds = max(7 * 24 * 60 * 60, settings.failed_retention_days * 24 * 60 * 60)

    def stream_key(self, queue_name: str, *, dead_letter: bool = False) -> str:
        _validate_queue_name(queue_name)
        suffix = ":dead-letter" if dead_letter else ""
        return f"{self.namespace}:stream:{queue_name}{suffix}"

    def event_stream_key(self) -> str:
        return f"{self.namespace}:stream:events"

    def quarantine_stream_key(self) -> str:
        return f"{self.namespace}:stream:quarantine"

    def _ensure_group(self, queue_name: str) -> None:
        key = self.stream_key(queue_name)
        try:
            self.client.xgroup_create(key, self.group, id="0-0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise StreamError(f"cannot create consumer group for {queue_name}: {exc}") from exc

    def _publish_deduplicated(
        self,
        stream_key: str,
        fields: Mapping[str, Any],
        *,
        outbox_event_id: str,
    ) -> str:
        if not outbox_event_id:
            raise StreamError("outbox_event_id is required")
        dedupe_key = f"{self.namespace}:outbox-published:{outbox_event_id}"
        arguments: list[str] = [str(self.dedupe_ttl_seconds)]
        for name, value in fields.items():
            arguments.extend((str(name), str(value)))
        try:
            result = self.client.eval(self._PUBLISH_SCRIPT, 2, dedupe_key, stream_key, *arguments)
        except Exception as exc:
            raise StreamError(f"Redis stream publish failed: {exc}") from exc
        return str(result)

    def publish_stage(
        self,
        queue_name: str,
        message: StageMessage,
        *,
        outbox_event_id: str,
        dead_letter: bool = False,
        dead_letter_fields: Mapping[str, Any] | None = None,
    ) -> str:
        _validate_queue_name(queue_name)
        fields = message.as_fields()
        fields["outbox_event_id"] = outbox_event_id
        if dead_letter_fields:
            for name, value in dead_letter_fields.items():
                if name in STAGE_MESSAGE_FIELDS or name == "outbox_event_id":
                    continue
                fields[f"dead_letter_{name}"] = str(value)
        return self._publish_deduplicated(
            self.stream_key(queue_name, dead_letter=dead_letter),
            fields,
            outbox_event_id=outbox_event_id,
        )

    def publish_event(
        self,
        topic: str,
        payload: Mapping[str, Any],
        *,
        outbox_event_id: str,
    ) -> str:
        fields = {
            "topic": topic,
            "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "outbox_event_id": outbox_event_id,
        }
        return self._publish_deduplicated(
            self.event_stream_key(),
            fields,
            outbox_event_id=outbox_event_id,
        )

    def read_stage(
        self,
        queue_name: str,
        *,
        consumer: str,
        count: int = 1,
        block_ms: int = 5_000,
        claim_idle_ms: int | None = None,
    ) -> list[StreamRecord]:
        _validate_queue_name(queue_name)
        self._ensure_group(queue_name)
        key = self.stream_key(queue_name)
        records: list[StreamRecord] = []
        if claim_idle_ms is not None and claim_idle_ms > 0:
            try:
                claimed = self.client.xautoclaim(
                    key,
                    self.group,
                    consumer,
                    min_idle_time=claim_idle_ms,
                    start_id="0-0",
                    count=count,
                )
                entries = claimed[1] if isinstance(claimed, (tuple, list)) and len(claimed) >= 2 else []
                records.extend(self._decode_entries(key, entries, deliveries=2))
            except Exception as exc:
                if "unknown command" not in str(exc).lower():
                    raise StreamError(f"Redis pending-message claim failed: {exc}") from exc
        if len(records) >= count:
            return records[:count]
        try:
            result = self.client.xreadgroup(
                self.group,
                consumer,
                {key: ">"},
                count=count - len(records),
                block=max(0, block_ms),
            )
        except Exception as exc:
            raise StreamError(f"Redis stream read failed: {exc}") from exc
        for stream, entries in result or []:
            records.extend(self._decode_entries(str(stream), entries))
        return records

    @staticmethod
    def _decode_entries(stream: str, entries: Sequence[Any], *, deliveries: int = 1) -> list[StreamRecord]:
        return [
            StreamRecord(
                stream=stream,
                message_id=str(message_id),
                fields={str(key): str(value) for key, value in fields.items()},
                deliveries=deliveries,
            )
            for message_id, fields in entries
        ]

    def ack(self, queue_name: str, message_ids: Sequence[str]) -> int:
        if not message_ids:
            return 0
        _validate_queue_name(queue_name)
        try:
            return int(self.client.xack(self.stream_key(queue_name), self.group, *message_ids))
        except Exception as exc:
            raise StreamError(f"Redis stream ack failed: {exc}") from exc

    def pending(self, queue_name: str) -> int:
        _validate_queue_name(queue_name)
        self._ensure_group(queue_name)
        try:
            summary = self.client.xpending(self.stream_key(queue_name), self.group)
        except Exception as exc:
            raise StreamError(f"Redis pending summary failed: {exc}") from exc
        if isinstance(summary, dict):
            return int(summary.get("pending", 0))
        if isinstance(summary, (tuple, list)) and summary:
            return int(summary[0])
        return 0

    def quarantine(self, queue_name: str, record: StreamRecord, *, reason: str) -> str:
        _validate_queue_name(queue_name)
        fields = _quarantine_fields(queue_name, record, reason)
        try:
            return str(self.client.xadd(self.quarantine_stream_key(), fields))
        except Exception as exc:
            raise StreamError(f"Redis quarantine publish failed: {exc}") from exc


@dataclass
class _PendingMemoryRecord:
    record: StreamRecord
    consumer: str
    delivered_at: float


class InMemoryStreamsBroker:
    """Deterministic Streams implementation used by queue chaos tests."""

    def __init__(self, namespace: str = "case-video") -> None:
        self.namespace = namespace
        self._records: dict[str, deque[StreamRecord]] = defaultdict(deque)
        self._pending: dict[str, dict[str, _PendingMemoryRecord]] = defaultdict(dict)
        self._dedupe: dict[str, str] = {}
        self._sequence = 0
        self._lock = threading.Lock()

    def stream_key(self, queue_name: str, *, dead_letter: bool = False) -> str:
        _validate_queue_name(queue_name)
        suffix = ":dead-letter" if dead_letter else ""
        return f"{self.namespace}:stream:{queue_name}{suffix}"

    def event_stream_key(self) -> str:
        return f"{self.namespace}:stream:events"

    def quarantine_stream_key(self) -> str:
        return f"{self.namespace}:stream:quarantine"

    def _publish(self, key: str, fields: Mapping[str, Any], outbox_event_id: str) -> str:
        with self._lock:
            prior = self._dedupe.get(outbox_event_id)
            if prior:
                return prior
            self._sequence += 1
            message_id = f"{self._sequence}-0"
            record = StreamRecord(
                stream=key,
                message_id=message_id,
                fields={str(name): str(value) for name, value in fields.items()},
            )
            self._records[key].append(record)
            self._dedupe[outbox_event_id] = message_id
            return message_id

    def publish_stage(
        self,
        queue_name: str,
        message: StageMessage,
        *,
        outbox_event_id: str,
        dead_letter: bool = False,
        dead_letter_fields: Mapping[str, Any] | None = None,
    ) -> str:
        fields = message.as_fields()
        fields["outbox_event_id"] = outbox_event_id
        if dead_letter_fields:
            for name, value in dead_letter_fields.items():
                if name in STAGE_MESSAGE_FIELDS or name == "outbox_event_id":
                    continue
                fields[f"dead_letter_{name}"] = str(value)
        return self._publish(
            self.stream_key(queue_name, dead_letter=dead_letter),
            fields,
            outbox_event_id,
        )

    def publish_event(
        self,
        topic: str,
        payload: Mapping[str, Any],
        *,
        outbox_event_id: str,
    ) -> str:
        return self._publish(
            self.event_stream_key(),
            {
                "topic": topic,
                "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                "outbox_event_id": outbox_event_id,
            },
            outbox_event_id,
        )

    def read_stage(
        self,
        queue_name: str,
        *,
        consumer: str,
        count: int = 1,
        block_ms: int = 5_000,
        claim_idle_ms: int | None = None,
    ) -> list[StreamRecord]:
        del block_ms
        key = self.stream_key(queue_name)
        now = time.monotonic()
        output: list[StreamRecord] = []
        with self._lock:
            if claim_idle_ms is not None and claim_idle_ms > 0:
                threshold = claim_idle_ms / 1000
                for message_id, pending in list(self._pending[key].items()):
                    if now - pending.delivered_at < threshold:
                        continue
                    claimed = StreamRecord(
                        stream=pending.record.stream,
                        message_id=pending.record.message_id,
                        fields=dict(pending.record.fields),
                        deliveries=pending.record.deliveries + 1,
                    )
                    self._pending[key][message_id] = _PendingMemoryRecord(claimed, consumer, now)
                    output.append(claimed)
                    if len(output) >= count:
                        return output
            while self._records[key] and len(output) < count:
                record = self._records[key].popleft()
                self._pending[key][record.message_id] = _PendingMemoryRecord(record, consumer, now)
                output.append(record)
        return output

    def ack(self, queue_name: str, message_ids: Sequence[str]) -> int:
        key = self.stream_key(queue_name)
        removed = 0
        with self._lock:
            for message_id in message_ids:
                if self._pending[key].pop(message_id, None) is not None:
                    removed += 1
        return removed

    def pending(self, queue_name: str) -> int:
        return len(self._pending[self.stream_key(queue_name)])

    def records(self, queue_name: str, *, dead_letter: bool = False) -> list[StreamRecord]:
        return list(self._records[self.stream_key(queue_name, dead_letter=dead_letter)])

    def event_records(self) -> list[StreamRecord]:
        return list(self._records[self.event_stream_key()])

    def quarantine_records(self) -> list[StreamRecord]:
        return list(self._records[self.quarantine_stream_key()])

    def quarantine(self, queue_name: str, record: StreamRecord, *, reason: str) -> str:
        _validate_queue_name(queue_name)
        digest = hashlib.sha256(
            json.dumps(record.fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self._publish(
            self.quarantine_stream_key(),
            _quarantine_fields(queue_name, record, reason),
            f"quarantine:{queue_name}:{record.message_id}:{digest}",
        )

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._pending.clear()
            self._dedupe.clear()


class OutboxDispatcher:
    def __init__(self, repository: PhaseCRepository, broker: StreamsBroker) -> None:
        self.repository = repository
        self.broker = broker

    def dispatch_batch(self, *, limit: int = 100) -> dict[str, int]:
        delivered = 0
        failed = 0
        for event in self.repository.pending_outbox(limit=limit):
            try:
                self._publish(event)
                self.repository.mark_outbox_delivered(event["tenant_id"], event["event_id"])
                delivered += 1
            except Exception as exc:
                self.repository.mark_outbox_failed(event["tenant_id"], event["event_id"], str(exc))
                failed += 1
        return {"delivered": delivered, "failed": failed}

    def _publish(self, event: Mapping[str, Any]) -> str:
        topic = str(event["topic"])
        payload = event["payload"]
        if not isinstance(payload, Mapping):
            raise StreamError("outbox payload must be an object")
        parts = topic.split(".")
        if len(parts) in {2, 3} and parts[0] == "queue" and parts[1] in QUEUE_NAMES:
            dead_letter = len(parts) == 3 and parts[2] == "dead_letter"
            if len(parts) == 3 and not dead_letter:
                raise StreamError(f"unsupported queue topic: {topic}")
            if dead_letter:
                stage_run = self.repository.get_stage_run(str(payload["tenant_id"]), str(payload["stage_run_id"]))
                message = StageMessage(
                    message_version=1,
                    tenant_id=str(payload["tenant_id"]),
                    job_id=str(payload["job_id"]),
                    stage_run_id=str(payload["stage_run_id"]),
                    expected_job_version=int(stage_run["expected_job_version"]),
                    input_snapshot_hash=str(stage_run["input_hash"]),
                    priority=str(stage_run["priority"]),
                    enqueued_at=utc_iso(),
                )
                return self.broker.publish_stage(
                    parts[1],
                    message,
                    outbox_event_id=str(event["event_id"]),
                    dead_letter=True,
                    dead_letter_fields={
                        "attempt": payload.get("attempt", stage_run["attempt"]),
                        "error_code": payload.get("error_code", stage_run.get("error_code") or "unknown"),
                    },
                )
            message = StageMessage.from_mapping(payload)
            return self.broker.publish_stage(
                parts[1],
                message,
                outbox_event_id=str(event["event_id"]),
            )
        return self.broker.publish_event(topic, payload, outbox_event_id=str(event["event_id"]))


@dataclass(frozen=True)
class StageExecutionResult:
    output_hash: str
    manifest: dict[str, Any] | None = None
    paid_result_key: str | None = None
    next_stage: str | None = None
    next_input_hash: str | None = None
    next_route_snapshot_hash: str | None = None
    next_config_snapshot_hash: str | None = None
    next_priority: str | None = None
    artifact_bundles: tuple[ArtifactBundleRegistration, ...] = ()
    model_runs: tuple[ModelRunRegistration, ...] = ()


StageHandler = Callable[[StageMessage, Mapping[str, Any]], StageExecutionResult]


class _Heartbeat:
    def __init__(
        self,
        repository: PhaseCRepository,
        message: StageMessage,
        worker_id: str,
        *,
        heartbeat_seconds: int,
        lease_seconds: int,
    ) -> None:
        self.repository = repository
        self.message = message
        self.worker_id = worker_id
        self.heartbeat_seconds = max(1, heartbeat_seconds)
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._error: Exception | None = None
        self._thread = threading.Thread(target=self._run, name=f"heartbeat-{message.stage_run_id}", daemon=True)

    def __enter__(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join(timeout=min(5, self.heartbeat_seconds + 1))

    def _run(self) -> None:
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                heartbeat = self.repository.heartbeat_stage_run(
                    self.message.tenant_id,
                    self.message.stage_run_id,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
                if heartbeat.get("cancel_requested"):
                    self._error = StageCanceled()
                    self._stop.set()
            except Exception as exc:  # surfaced to the main worker before commit
                self._error = exc
                self._stop.set()

    def ensure_owned(self) -> None:
        if self._error is not None:
            if isinstance(self._error, StageExecutionError):
                raise self._error
            raise LeaseLost(str(self._error)) from self._error


class StageWorker:
    def __init__(
        self,
        repository: PhaseCRepository,
        broker: StreamsBroker,
        *,
        queue_name: str,
        worker_id: str,
        handler: StageHandler,
        heartbeat_seconds: int = 15,
        lease_seconds: int = 90,
        max_attempts: int = 3,
    ) -> None:
        _validate_queue_name(queue_name)
        self.repository = repository
        self.broker = broker
        self.queue_name = queue_name
        self.worker_id = worker_id
        self.handler = handler
        self.heartbeat_seconds = heartbeat_seconds
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def _message_mismatch(self, message: StageMessage) -> str | None:
        try:
            stage_run = self.repository.get_stage_run(message.tenant_id, message.stage_run_id)
        except RepositoryError as exc:
            return f"stage run lookup failed: {exc}"
        checks = (
            (stage_run.get("job_id"), message.job_id, "job_id"),
            (stage_run.get("queue_name"), self.queue_name, "queue_name"),
            (stage_run.get("expected_job_version"), message.expected_job_version, "expected_job_version"),
            (stage_run.get("input_hash"), message.input_snapshot_hash, "input_snapshot_hash"),
        )
        for actual, expected, field in checks:
            if actual != expected:
                return f"{field} does not match the authoritative stage run"
        try:
            expected_queue = queue_for_stage(str(stage_run.get("stage", "")))
        except StreamError as exc:
            return str(exc)
        if expected_queue != self.queue_name:
            return "stage is routed to a different worker queue"
        return None

    def _quarantine_and_ack(self, record: StreamRecord, reason: str) -> dict[str, Any]:
        self.broker.quarantine(self.queue_name, record, reason=reason)
        self.broker.ack(self.queue_name, [record.message_id])
        return {
            "outcome": "quarantined",
            "reason": reason,
            "message_id": record.message_id,
        }

    def process_one(self, *, block_ms: int = 5_000, claim_idle_ms: int | None = None) -> dict[str, Any] | None:
        records = self.broker.read_stage(
            self.queue_name,
            consumer=self.worker_id,
            count=1,
            block_ms=block_ms,
            claim_idle_ms=claim_idle_ms,
        )
        if not records:
            return None
        record = records[0]
        try:
            message = record.stage_message
        except InvalidStageMessage as exc:
            return self._quarantine_and_ack(record, str(exc))
        mismatch = self._message_mismatch(message)
        if mismatch is not None:
            return self._quarantine_and_ack(record, mismatch)
        try:
            claim = self.repository.claim_stage_run(
                message.tenant_id,
                message.stage_run_id,
                worker_id=self.worker_id,
                lease_seconds=self.lease_seconds,
            )
        except LeaseConflict as exc:
            self.broker.ack(self.queue_name, [record.message_id])
            return {"outcome": "stale_message", "reason": str(exc), "stage_run_id": message.stage_run_id}
        if claim.get("claim") != "claimed":
            self.broker.ack(self.queue_name, [record.message_id])
            return {"outcome": str(claim.get("claim")), "stage_run_id": message.stage_run_id}
        try:
            with _Heartbeat(
                self.repository,
                message,
                self.worker_id,
                heartbeat_seconds=self.heartbeat_seconds,
                lease_seconds=self.lease_seconds,
            ) as heartbeat:
                result = self.handler(message, claim)
                heartbeat.ensure_owned()
            committed = self.repository.complete_stage_run(
                message.tenant_id,
                message.stage_run_id,
                worker_id=self.worker_id,
                output_hash=result.output_hash,
                manifest=result.manifest,
                paid_result_key=result.paid_result_key,
                next_stage=result.next_stage,
                next_queue_name=queue_for_stage(result.next_stage) if result.next_stage else None,
                next_input_hash=result.next_input_hash,
                next_route_snapshot_hash=result.next_route_snapshot_hash,
                next_config_snapshot_hash=result.next_config_snapshot_hash,
                next_priority=result.next_priority or message.priority,
                artifact_bundles=result.artifact_bundles,
                model_runs=result.model_runs,
            )
            self.broker.ack(self.queue_name, [record.message_id])
            return {"outcome": committed.get("commit", "succeeded"), "stage_run_id": message.stage_run_id}
        except BudgetApprovalRequired:
            paused = self.repository.pause_stage_run_for_budget(
                message.tenant_id,
                message.stage_run_id,
                worker_id=self.worker_id,
            )
            self.broker.ack(self.queue_name, [record.message_id])
            return {
                "outcome": "waiting_approval",
                "stage_run_id": message.stage_run_id,
                "error_code": paused.get("error_code", "budget_approval_required"),
            }
        except Exception as exc:
            retryable = exc.retryable if isinstance(exc, StageExecutionError) else True
            code = exc.code if isinstance(exc, StageExecutionError) else "stage_execution_failed"
            try:
                failed = self.repository.fail_stage_run(
                    message.tenant_id,
                    message.stage_run_id,
                    worker_id=self.worker_id,
                    error_code=code,
                    error_message=str(exc),
                    retryable=retryable,
                    max_attempts=self.max_attempts,
                )
            except Exception:
                # Leave the stream entry pending when the authoritative DB write
                # fails. It can be reclaimed after its idle/lease timeout.
                raise
            self.broker.ack(self.queue_name, [record.message_id])
            if failed.get("canceled"):
                return {
                    "outcome": "canceled",
                    "stage_run_id": message.stage_run_id,
                    "error_code": "canceled",
                }
            return {
                "outcome": "dead_letter" if failed.get("dead_letter") else "retry_queued",
                "stage_run_id": message.stage_run_id,
                "error_code": code,
            }


class QueueRecoveryService:
    def __init__(self, repository: PhaseCRepository, dispatcher: OutboxDispatcher, *, max_attempts: int) -> None:
        self.repository = repository
        self.dispatcher = dispatcher
        self.max_attempts = max_attempts

    def reap_and_dispatch(self) -> dict[str, Any]:
        recovered = self.repository.reap_expired_leases(max_attempts=self.max_attempts)
        dispatched = self.dispatcher.dispatch_batch()
        return {"recovered": recovered, **dispatched}

    def rebuild_and_dispatch(self) -> dict[str, int]:
        rebuilt = self.repository.rebuild_queue_outbox()
        dispatched = self.dispatcher.dispatch_batch()
        return {"rebuilt": rebuilt, **dispatched}

    def recover_after_restore(self) -> dict[str, Any]:
        """Recover authoritative work after restoring into an empty Redis.

        Restored workers no longer exist, therefore running leases are expired
        immediately. Queued runs then receive fresh outbox intents and all
        pending intents are drained into the empty broker.
        """

        expired_leases = self.repository.expire_running_leases_for_recovery()
        recovered = self.repository.reap_expired_leases(max_attempts=self.max_attempts)
        rebuilt = self.repository.rebuild_queue_outbox()
        delivered = 0
        failed = 0
        while True:
            batch = self.dispatcher.dispatch_batch(limit=500)
            delivered += batch["delivered"]
            failed += batch["failed"]
            if batch["delivered"] == 0 or batch["failed"]:
                break
        return {
            "expired_leases": expired_leases,
            "recovered": recovered,
            "rebuilt": rebuilt,
            "delivered": delivered,
            "failed": failed,
        }


def build_streams_broker(settings: Settings) -> RedisStreamsBroker:
    return RedisStreamsBroker(settings)


def _validate_queue_name(queue_name: str) -> None:
    if queue_name not in QUEUE_NAMES:
        raise StreamError(f"unsupported queue: {queue_name}")


def _quarantine_fields(queue_name: str, record: StreamRecord, reason: str) -> dict[str, str]:
    serialized = json.dumps(
        record.fields,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    output = {
        "queue": queue_name,
        "source_message_id": record.message_id,
        "reason": reason[:1000],
        "payload_sha256": hashlib.sha256(serialized).hexdigest(),
        "quarantined_at": utc_iso(),
    }
    # Preserve identifiers needed for an operator to inspect/replay an unknown
    # version, but never copy unexpected field values into Redis or logs.
    for name in STAGE_MESSAGE_FIELDS | STREAM_METADATA_FIELDS:
        value = record.fields.get(name)
        if value is not None:
            output[name] = str(value)[:512]
    unexpected = sorted(set(record.fields) - STAGE_MESSAGE_FIELDS - STREAM_METADATA_FIELDS)
    if unexpected:
        output["unexpected_fields"] = ",".join(unexpected)[:1000]
    return output
