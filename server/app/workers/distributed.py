from __future__ import annotations

import argparse
import json
import logging
import signal
import socket
import time
import uuid
from dataclasses import dataclass

from server.app.core.config import Settings, load_settings
from server.app.persistence.database import Database
from server.app.persistence.object_store import ObjectStore, object_store_from_settings
from server.app.persistence.repository import PhaseCRepository
from server.app.services.distributed_pipeline import DistributedStageExecutor
from server.app.services.model_gateway import ModelGateway
from server.app.services.streams import QUEUE_NAMES, RedisStreamsBroker, StageWorker, StreamsBroker


LOGGER = logging.getLogger("case-video-stage-worker")


@dataclass
class StopSignal:
    requested: bool = False

    def install(self) -> None:
        def stop(_: int, __: object) -> None:
            self.requested = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)


def default_worker_id(queue_name: str) -> str:
    host = socket.gethostname().split(".", 1)[0][:48] or "worker"
    return f"{queue_name}-{host}-{uuid.uuid4().hex[:10]}"


def build_stage_worker(
    settings: Settings,
    repository: PhaseCRepository,
    broker: StreamsBroker,
    object_store: ObjectStore,
    *,
    queue_name: str,
    worker_id: str,
) -> StageWorker:
    if settings.deployment_mode != "distributed":
        raise RuntimeError("distributed stage workers require CASE_VIDEO_DEPLOYMENT_MODE=distributed")
    ModelGateway(settings).validate_required_routes(
        require_provider_config=settings.require_model_config or not settings.dry_run
    )
    executor = DistributedStageExecutor(settings, repository, object_store)
    return StageWorker(
        repository,
        broker,
        queue_name=queue_name,
        worker_id=worker_id,
        handler=executor,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        lease_seconds=settings.worker_lease_seconds,
        max_attempts=settings.worker_max_attempts,
    )


def run_stage_worker(
    queue_name: str,
    *,
    once: bool = False,
    idle_seconds: float = 0.5,
    worker_id: str | None = None,
) -> int:
    if queue_name not in QUEUE_NAMES:
        raise ValueError(f"unsupported queue: {queue_name}")
    settings = load_settings()
    database = Database.from_settings(settings)
    database.check_schema()
    repository = PhaseCRepository(database)
    broker = RedisStreamsBroker(settings)
    object_store = object_store_from_settings(settings)
    identity = worker_id or default_worker_id(queue_name)
    worker = build_stage_worker(
        settings,
        repository,
        broker,
        object_store,
        queue_name=queue_name,
        worker_id=identity,
    )
    stop = StopSignal()
    stop.install()
    processed = 0
    reclaim_after_ms = max(1, settings.worker_lease_seconds * 1_000)
    LOGGER.info(
        "worker_started=%s",
        json.dumps(
            {"queue": queue_name, "worker_id": identity, "deployment_mode": settings.deployment_mode},
            ensure_ascii=False,
            sort_keys=True,
        ),
    )
    try:
        while not stop.requested:
            result = worker.process_one(
                block_ms=0 if once else min(5_000, max(250, int(idle_seconds * 1_000))),
                claim_idle_ms=reclaim_after_ms,
            )
            if result is not None:
                processed += 1
                LOGGER.info(
                    "stage_cycle=%s",
                    json.dumps(
                        {"queue": queue_name, "worker_id": identity, **result},
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    ),
                )
            if once:
                break
            if result is None:
                time.sleep(max(0.05, min(idle_seconds, 5.0)))
    finally:
        database.dispose()
        LOGGER.info(
            "worker_stopped=%s",
            json.dumps(
                {"queue": queue_name, "worker_id": identity, "processed": processed},
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    return processed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Run a Phase C distributed stage worker")
    parser.add_argument("queue", choices=QUEUE_NAMES)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--idle", type=float, default=0.5)
    parser.add_argument("--worker-id")
    args = parser.parse_args()
    run_stage_worker(
        args.queue,
        once=args.once,
        idle_seconds=args.idle,
        worker_id=args.worker_id,
    )


if __name__ == "__main__":
    main()
