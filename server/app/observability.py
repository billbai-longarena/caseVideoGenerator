from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from fastapi import Request

from server.app.core.config import Settings
from server.app.persistence.object_store import ObjectStore
from server.app.persistence.repository import PhaseCRepository


TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$")
LOGGER = logging.getLogger("case-video-api")


@dataclass(frozen=True)
class RequestObservation:
    method: str
    route: str
    status_code: int
    duration_seconds: float


@dataclass(frozen=True)
class GaugeSample:
    name: str
    value: float
    labels: Mapping[str, str]


class MetricsRegistry:
    """Small dependency-free Prometheus registry with low-cardinality labels."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._lock = threading.Lock()

    def inc(self, name: str, value: float = 1, **labels: str) -> None:
        key = (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))
        with self._lock:
            self._counters[key] += value

    def set(self, name: str, value: float, **labels: str) -> None:
        key = (name, tuple(sorted((str(k), str(v)) for k, v in labels.items())))
        with self._lock:
            self._gauges[key] = value

    def replace_gauges(self, names: Iterable[str], samples: Iterable[GaugeSample]) -> None:
        """Atomically replace a family of gauges after one control-plane scrape.

        Replacing the complete family prevents removed queue/status values from
        surviving forever as stale Prometheus series.
        """

        selected = frozenset(names)
        encoded = {
            (
                sample.name,
                tuple(sorted((str(key), str(value)) for key, value in sample.labels.items())),
            ): float(sample.value)
            for sample in samples
            if sample.name in selected
        }
        with self._lock:
            self._gauges = {
                key: value
                for key, value in self._gauges.items()
                if key[0] not in selected
            }
            self._gauges.update(encoded)

    def observe_request(self, observation: RequestObservation) -> None:
        labels = {
            "method": observation.method,
            "route": observation.route,
            "status_class": f"{observation.status_code // 100}xx",
        }
        self.inc("casevideo_http_requests_total", **labels)
        self.inc(
            "casevideo_http_request_duration_seconds_sum",
            observation.duration_seconds,
            **labels,
        )
        self.inc("casevideo_http_request_duration_seconds_count", **labels)
        if observation.status_code == 401:
            self.inc("casevideo_authentication_failures_total", route=observation.route)
        elif observation.status_code == 403:
            self.inc("casevideo_authorization_denials_total", route=observation.route)

    def render(self) -> str:
        lines = [
            "# HELP casevideo_http_requests_total HTTP requests handled.",
            "# TYPE casevideo_http_requests_total counter",
            "# HELP casevideo_http_request_duration_seconds_sum HTTP request duration sum.",
            "# TYPE casevideo_http_request_duration_seconds_sum counter",
            "# HELP casevideo_http_request_duration_seconds_count HTTP request duration count.",
            "# TYPE casevideo_http_request_duration_seconds_count counter",
            "# HELP casevideo_authentication_failures_total Requests rejected because authentication failed.",
            "# TYPE casevideo_authentication_failures_total counter",
            "# HELP casevideo_authorization_denials_total Authenticated requests rejected by authorization policy.",
            "# TYPE casevideo_authorization_denials_total counter",
            "# HELP casevideo_metrics_collection_success Whether the latest Phase C metrics collection succeeded.",
            "# TYPE casevideo_metrics_collection_success gauge",
            "# HELP casevideo_metrics_collection_timestamp_seconds Unix timestamp of the latest Phase C metrics collection.",
            "# TYPE casevideo_metrics_collection_timestamp_seconds gauge",
            "# HELP casevideo_tenants Number of active tenants aggregated by the control plane.",
            "# TYPE casevideo_tenants gauge",
            "# HELP casevideo_jobs Number of jobs by status.",
            "# TYPE casevideo_jobs gauge",
            "# HELP casevideo_stage_runs Number of stage runs by queue and status.",
            "# TYPE casevideo_stage_runs gauge",
            "# HELP casevideo_queue_depth Number of queued stage runs by queue.",
            "# TYPE casevideo_queue_depth gauge",
            "# HELP casevideo_queue_oldest_age_seconds Age of the oldest queued stage run by queue.",
            "# TYPE casevideo_queue_oldest_age_seconds gauge",
            "# HELP casevideo_dead_letters Number of dead-letter stage runs by queue.",
            "# TYPE casevideo_dead_letters gauge",
            "# HELP casevideo_worker_leases Number of worker leases by state.",
            "# TYPE casevideo_worker_leases gauge",
            "# HELP casevideo_workers Number of workers by state without worker identifiers.",
            "# TYPE casevideo_workers gauge",
            "# HELP casevideo_outbox_events Number of outbox events by state.",
            "# TYPE casevideo_outbox_events gauge",
            "# HELP casevideo_budget_waiting_jobs Number of jobs waiting for budget approval.",
            "# TYPE casevideo_budget_waiting_jobs gauge",
            "# HELP casevideo_model_route_ready Whether a required model route is configured.",
            "# TYPE casevideo_model_route_ready gauge",
            "# HELP casevideo_dependency_ready Whether a required control-plane dependency is readable.",
            "# TYPE casevideo_dependency_ready gauge",
        ]
        with self._lock:
            values = [*self._counters.items(), *self._gauges.items()]
        for (name, labels), value in sorted(values):
            suffix = ""
            if labels:
                encoded = ",".join(f'{key}="{_escape_label(item)}"' for key, item in labels)
                suffix = "{" + encoded + "}"
            lines.append(f"{name}{suffix} {_format_number(value)}")
        return "\n".join(lines) + "\n"


PHASE_C_GAUGE_NAMES = frozenset(
    {
        "casevideo_metrics_collection_success",
        "casevideo_metrics_collection_timestamp_seconds",
        "casevideo_tenants",
        "casevideo_jobs",
        "casevideo_stage_runs",
        "casevideo_queue_depth",
        "casevideo_queue_oldest_age_seconds",
        "casevideo_dead_letters",
        "casevideo_worker_leases",
        "casevideo_workers",
        "casevideo_outbox_events",
        "casevideo_budget_waiting_jobs",
        "casevideo_model_route_ready",
        "casevideo_dependency_ready",
    }
)


class PhaseCMetricsCollector:
    """Aggregate Phase C control-plane state into low-cardinality gauges."""

    def __init__(
        self,
        settings: Settings,
        repository: PhaseCRepository,
        object_store: ObjectStore,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.object_store = object_store

    def collect(self, registry: MetricsRegistry) -> None:
        collected_at = time.time()
        samples: list[GaugeSample] = []
        try:
            tenants = self.repository.list_tenants(active_only=True)
            jobs: dict[str, int] = defaultdict(int)
            stage_runs: dict[tuple[str, str], int] = defaultdict(int)
            queue_depth: dict[str, int] = defaultdict(int)
            queue_oldest: dict[str, float] = defaultdict(float)
            dead_letters: dict[str, int] = defaultdict(int)
            leases: dict[str, int] = defaultdict(int)
            outbox: dict[str, int] = defaultdict(int)
            worker_states: dict[str, set[str]] = {
                "active": set(),
                "stale": set(),
            }
            budget_waiting = 0

            for tenant in tenants:
                snapshot = self.repository.operations_snapshot(str(tenant["tenant_id"]))
                for status, count in snapshot["jobs_by_status"].items():
                    jobs[str(status)] += int(count)
                for queue in snapshot["queues"]:
                    queue_name = str(queue["queue"])
                    queue_depth[queue_name] += int(queue["queued"])
                    dead_letters[queue_name] += int(queue["dead_letter"])
                    age = queue.get("oldest_queued_age_seconds")
                    if age is not None:
                        queue_oldest[queue_name] = max(queue_oldest[queue_name], float(age))
                    for status, count in queue["by_status"].items():
                        stage_runs[(queue_name, str(status))] += int(count)
                leases["active"] += int(snapshot["leases"]["active"])
                leases["expired"] += int(snapshot["leases"]["expired"])
                outbox["pending"] += int(snapshot["outbox"]["pending"])
                outbox["failed"] += int(snapshot["outbox"]["failed"])
                budget_waiting += int(snapshot["budget_waiting"])
                for worker in snapshot["workers"]:
                    worker_id = str(worker["worker_id"])
                    if int(worker["active_leases"]) > 0:
                        worker_states["active"].add(worker_id)
                    else:
                        worker_states["stale"].add(worker_id)

            worker_states["stale"].difference_update(worker_states["active"])

            samples.append(GaugeSample("casevideo_tenants", len(tenants), {}))
            samples.extend(
                GaugeSample("casevideo_jobs", count, {"status": status})
                for status, count in jobs.items()
            )
            samples.extend(
                GaugeSample(
                    "casevideo_stage_runs",
                    count,
                    {"queue": queue_name, "status": status},
                )
                for (queue_name, status), count in stage_runs.items()
            )
            for queue_name in ("planning", "media", "render", "qa"):
                samples.extend(
                    (
                        GaugeSample(
                            "casevideo_queue_depth",
                            queue_depth[queue_name],
                            {"queue": queue_name},
                        ),
                        GaugeSample(
                            "casevideo_queue_oldest_age_seconds",
                            queue_oldest[queue_name],
                            {"queue": queue_name},
                        ),
                        GaugeSample(
                            "casevideo_dead_letters",
                            dead_letters[queue_name],
                            {"queue": queue_name},
                        ),
                    )
                )
            samples.extend(
                GaugeSample("casevideo_worker_leases", count, {"state": state})
                for state, count in (("active", leases["active"]), ("expired", leases["expired"]))
            )
            samples.extend(
                GaugeSample("casevideo_workers", len(worker_states[state]), {"state": state})
                for state in ("active", "stale")
            )
            samples.extend(
                GaugeSample("casevideo_outbox_events", count, {"state": state})
                for state, count in (("pending", outbox["pending"]), ("failed", outbox["failed"]))
            )
            samples.append(GaugeSample("casevideo_budget_waiting_jobs", budget_waiting, {}))
            samples.extend(self._route_samples())
            next(iter(self.object_store.list("readiness-probe")), None)
            samples.extend(
                (
                    GaugeSample("casevideo_dependency_ready", 1, {"dependency": "database"}),
                    GaugeSample("casevideo_dependency_ready", 1, {"dependency": "object_store"}),
                )
            )
            samples.append(GaugeSample("casevideo_metrics_collection_success", 1, {}))
        except Exception:
            LOGGER.exception("phase_c_metrics_collection_failed")
            samples = [
                GaugeSample("casevideo_metrics_collection_success", 0, {}),
                GaugeSample(
                    "casevideo_dependency_ready",
                    0,
                    {"dependency": "control_plane"},
                ),
            ]
        samples.append(
            GaugeSample("casevideo_metrics_collection_timestamp_seconds", collected_at, {})
        )
        registry.replace_gauges(PHASE_C_GAUGE_NAMES, samples)

    def _route_samples(self) -> list[GaugeSample]:
        samples: list[GaugeSample] = []
        for name, route in self.settings.model_routes.items():
            credential_ready = bool(route.api_key_env and os.getenv(route.api_key_env))
            endpoint_ready = bool(
                route.endpoint if route.provider == "azure_anthropic" else route.base_url
            )
            request_model_ready = bool(
                route.request_model
                and (
                    route.provider != "azure_anthropic"
                    or str(route.request_model).startswith("claude-")
                )
            )
            samples.append(
                GaugeSample(
                    "casevideo_model_route_ready",
                    1 if credential_ready and endpoint_ready and request_model_ready else 0,
                    {"route": name, "provider": route.provider},
                )
            )
        return samples


def trace_id_for_request(request: Request) -> str:
    match = TRACEPARENT_RE.match(request.headers.get("traceparent", "").strip().lower())
    return match.group(1) if match else uuid.uuid4().hex


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return str(path) if path else "unmatched"


def log_request(
    request: Request,
    *,
    status_code: int,
    duration_seconds: float,
    structured: bool,
) -> None:
    record: Mapping[str, Any] = {
        "event": "http.request",
        "method": request.method,
        "route": route_template(request),
        "status_code": status_code,
        "duration_ms": round(duration_seconds * 1000, 3),
        "request_id": getattr(request.state, "request_id", None),
        "trace_id": getattr(request.state, "trace_id", None),
        "tenant_id": getattr(getattr(request.state, "principal", None), "tenant_id", None),
        "actor_id": getattr(getattr(request.state, "principal", None), "actor_id", None),
    }
    if structured:
        LOGGER.info(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    else:
        LOGGER.info(
            "%s %s status=%s duration_ms=%s request_id=%s trace_id=%s",
            record["method"],
            record["route"],
            record["status_code"],
            record["duration_ms"],
            record["request_id"],
            record["trace_id"],
        )


def monotonic_seconds() -> float:
    return time.monotonic()


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else format(value, ".12g")
