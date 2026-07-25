from __future__ import annotations

import argparse
import logging
import time

from server.app.core.config import load_settings
from server.app.services.pipeline import CaseVideoPipeline
from server.app.services.queue import build_queue
from server.app.services.storage import JobStorage


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("case-video-worker")


def run_worker(once: bool = False, idle_sleep_seconds: float = 1.0) -> None:
    settings = load_settings()
    storage = JobStorage(settings)
    queue = build_queue(settings)
    pipeline = CaseVideoPipeline(settings, storage)
    while True:
        job_id = queue.dequeue(timeout_seconds=5)
        if not job_id:
            if once:
                return
            time.sleep(idle_sleep_seconds)
            continue
        LOGGER.info("processing job_id=%s", job_id)
        manifest = storage.read_manifest(job_id)
        force = bool(manifest.get("force_requested"))
        pipeline.run(job_id, force=force)
        if once:
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the case video pipeline worker.")
    parser.add_argument("--once", action="store_true", help="Process one queued job and exit.")
    args = parser.parse_args()
    run_worker(once=args.once)


if __name__ == "__main__":
    main()
