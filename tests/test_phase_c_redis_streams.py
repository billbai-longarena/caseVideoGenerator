from __future__ import annotations

import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from server.app.core.config import load_settings
from server.app.services.streams import RedisStreamsBroker, StageMessage


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


@pytest.fixture()
def redis_broker(tmp_path: Path):
    executable = shutil.which("redis-server")
    if executable is None:
        pytest.skip("redis-server is not installed")
    port = free_port()
    process = subprocess.Popen(
        [
            executable,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(tmp_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    settings = replace(
        load_settings(),
        redis_url=f"redis://127.0.0.1:{port}/0",
        redis_namespace=f"test-{uuid.uuid4().hex}",
        worker_consumer_group="contract-workers",
    )
    broker = RedisStreamsBroker(settings)
    for _ in range(100):
        try:
            if broker.client.ping():
                break
        except Exception:
            time.sleep(0.02)
    else:
        process.terminate()
        raise RuntimeError("test Redis did not become ready")
    try:
        yield broker
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def message() -> StageMessage:
    return StageMessage(
        message_version=1,
        tenant_id="ten_a",
        job_id="job_a",
        stage_run_id="run_a",
        expected_job_version=1,
        input_snapshot_hash="a" * 64,
        priority="normal",
        enqueued_at=datetime.now(timezone.utc).isoformat(),
    )


def test_real_redis_atomic_outbox_dedupe_consumer_group_and_ack(redis_broker: RedisStreamsBroker) -> None:
    first = redis_broker.publish_stage("planning", message(), outbox_event_id="out_a")
    repeated = redis_broker.publish_stage("planning", message(), outbox_event_id="out_a")
    assert repeated == first
    assert redis_broker.client.xlen(redis_broker.stream_key("planning")) == 1

    records = redis_broker.read_stage("planning", consumer="worker_a", block_ms=0)
    assert len(records) == 1
    assert records[0].stage_message.stage_run_id == "run_a"
    assert redis_broker.pending("planning") == 1
    assert redis_broker.ack("planning", [records[0].message_id]) == 1
    assert redis_broker.pending("planning") == 0


def test_real_redis_auto_claims_abandoned_pending_message(redis_broker: RedisStreamsBroker) -> None:
    redis_broker.publish_stage("render", message(), outbox_event_id="out_render")
    original = redis_broker.read_stage("render", consumer="dead_worker", block_ms=0)[0]
    time.sleep(0.01)
    claimed = redis_broker.read_stage(
        "render",
        consumer="recovery_worker",
        block_ms=0,
        claim_idle_ms=1,
    )
    assert [record.message_id for record in claimed] == [original.message_id]
    assert claimed[0].deliveries >= 2
    assert redis_broker.ack("render", [original.message_id]) == 1


def test_real_redis_dead_letter_is_separate_from_work_stream(redis_broker: RedisStreamsBroker) -> None:
    redis_broker.publish_stage(
        "qa",
        message(),
        outbox_event_id="out_dlq",
        dead_letter=True,
        dead_letter_fields={"attempt": 3, "error_code": "qa_failed"},
    )
    assert redis_broker.client.xlen(redis_broker.stream_key("qa")) == 0
    assert redis_broker.client.xlen(redis_broker.stream_key("qa", dead_letter=True)) == 1
