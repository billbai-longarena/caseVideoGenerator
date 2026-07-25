from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from server.app.core.config import get_settings
from server.app.persistence.artifact_commit import ArtifactCommitService
from server.app.persistence.database import Database
from server.app.persistence.importer import LegacyJobImporter
from server.app.persistence.object_store import object_store_from_settings
from server.app.persistence.repository import PhaseCRepository


def main() -> int:
    parser = argparse.ArgumentParser(description="Import filesystem jobs into Phase C persistence")
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--tenant-id")
    parser.add_argument("--actor-id", default="migration")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--shadow-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    settings = get_settings()
    database = Database.from_settings(settings)
    database.check_schema()
    repository = PhaseCRepository(database)
    importer = LegacyJobImporter(
        repository,
        ArtifactCommitService(repository, object_store_from_settings(settings)),
    )
    report = importer.run(
        args.source_root,
        tenant_id=args.tenant_id or settings.default_tenant_id,
        actor_id=args.actor_id,
        dry_run=args.dry_run,
        shadow_only=args.shadow_only,
    )
    payload = report.to_dict()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.report:
        destination = args.report.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(destination.parent),
            delete=False,
        ) as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, destination)
    database.dispose()
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
