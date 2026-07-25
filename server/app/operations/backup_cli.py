from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from server.app.core.config import load_settings
from server.app.operations.backup import BackupService, RestoreService, verify_backup
from server.app.persistence.database import Database
from server.app.persistence.object_store import object_store_from_settings
from server.app.services.streams import RedisStreamsBroker


def main() -> int:
    parser = argparse.ArgumentParser(description="Create, verify, or restore a Phase C portable backup")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument(
        "destination",
        nargs="?",
        type=Path,
        default=Path(os.getenv("CASE_VIDEO_BACKUP_DIRECTORY", "/backups/manual")),
    )
    create.add_argument("--backup-id")

    verify = subparsers.add_parser("verify")
    verify.add_argument("backup_dir", type=Path)

    restore = subparsers.add_parser("restore")
    restore.add_argument("backup_dir", type=Path)
    restore.add_argument("--confirm", default=os.getenv("CASE_VIDEO_RESTORE_CONFIRM", ""))
    args = parser.parse_args()

    settings = load_settings()
    if args.command == "verify":
        report = verify_backup(args.backup_dir)
    elif args.command == "create":
        database = Database.from_settings(settings)
        try:
            report = BackupService(database, object_store_from_settings(settings)).create(
                args.destination,
                backup_id=args.backup_id,
            )
        finally:
            database.dispose()
    else:
        report = RestoreService(
            target_database_url=settings.database_url,
            target_store=object_store_from_settings(settings),
            broker=RedisStreamsBroker(settings),
            max_attempts=settings.worker_max_attempts,
        ).restore(args.backup_dir, confirmation=args.confirm)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
