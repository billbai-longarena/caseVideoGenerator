from __future__ import annotations

import argparse
import json
import logging
import signal
import time
from dataclasses import dataclass

from server.app.core.config import load_settings
from server.app.persistence.database import Database
from server.app.persistence.repository import PhaseCRepository
from server.app.services.streams import OutboxDispatcher, QueueRecoveryService, RedisStreamsBroker


LOGGER = logging.getLogger("case-video-control-worker")


@dataclass
class StopSignal:
    requested: bool = False

    def install(self) -> None:
        def stop(_: int, __: object) -> None:
            self.requested = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)


def run_control_worker(
    mode: str,
    *,
    once: bool = False,
    interval_seconds: float = 1.0,
) -> int:
    settings = load_settings()
    database = Database.from_settings(settings)
    database.check_schema()
    repository = PhaseCRepository(database)
    dispatcher = OutboxDispatcher(repository, RedisStreamsBroker(settings))
    recovery = QueueRecoveryService(
        repository,
        dispatcher,
        max_attempts=settings.worker_max_attempts,
    )
    stop = StopSignal()
    stop.install()
    processed = 0
    try:
        while not stop.requested:
            if mode == "dispatch":
                report = dispatcher.dispatch_batch()
                processed += report["delivered"]
            elif mode == "reap":
                report = recovery.reap_and_dispatch()
                processed += len(report["recovered"])
            elif mode == "rebuild":
                report = recovery.rebuild_and_dispatch()
                processed += report["rebuilt"]
            else:  # protected by argparse; retained for direct callers
                raise ValueError(f"unsupported control worker mode: {mode}")
            LOGGER.info("control_cycle=%s", json.dumps(report, ensure_ascii=False, default=str))
            if once or mode == "rebuild":
                break
            if report.get("delivered", 0) == 0 and not report.get("recovered"):
                time.sleep(max(0.05, interval_seconds))
    finally:
        database.dispose()
    return processed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Run Phase C outbox/reaper/rebuild control workers")
    parser.add_argument("mode", choices=("dispatch", "reap", "rebuild"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    run_control_worker(args.mode, once=args.once, interval_seconds=args.interval)


if __name__ == "__main__":
    main()
