from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.app.core.config import load_settings
from server.app.operations.upgrade import (
    UpgradeSnapshotService,
    read_snapshot,
    write_snapshot,
)
from server.app.persistence.database import Database


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Capture or verify immutable in-flight job snapshots during an upgrade"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("snapshot", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("snapshot", type=Path)
    verify.add_argument("--report", type=Path)

    args = parser.parse_args()
    settings = load_settings()
    database = Database.from_settings(settings)
    try:
        service = UpgradeSnapshotService(database)
        if args.command == "capture":
            result = service.capture()
            write_snapshot(args.snapshot, result)
        else:
            result = service.verify(read_snapshot(args.snapshot))
            if args.report:
                write_snapshot(args.report, result)
    finally:
        database.dispose()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if args.command == "capture" or result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
