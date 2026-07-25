# Backup and disaster recovery runbook

Owner: platform operations. Security and application engineering join any real
restore. The database and object store are authoritative; Redis is disposable.

## Targets and prerequisites

- PostgreSQL: daily full backup plus continuous WAL/PITR, RPO 15 minutes.
- Full service recovery: RTO 4 hours.
- Object storage: versioning or soft delete enabled, encrypted at rest, and
  replicated outside the primary failure domain.
- Redis data is never treated as a backup source.
- A portable application backup contains a database snapshot, every object,
  and `backup-manifest.json` with immutable sizes and SHA-256 values. It is the
  quarterly restore-drill format; production still needs managed WAL/PITR.

Before starting, freeze retention deletion and record incident/drill owner,
target recovery time, image digest, database endpoint identity, and object
bucket identity. Never paste credentials or connection strings into tickets or
command output.

## Create and verify a portable backup

Choose a unique immutable directory. Existing directories are rejected.

```bash
CASE_VIDEO_BACKUP_DIRECTORY=/backups/drill-YYYYMMDD-HHMM \
  docker compose --profile operations run --rm backup

docker compose --profile operations run --rm backup \
  python -m server.app.operations.backup_cli verify \
  /backups/drill-YYYYMMDD-HHMM
```

Copy the resulting directory to the protected backup system. Confirm its
retention, encryption, versioning, and cross-failure-domain replication there.
The command must finish with no database or object hash mismatch.

## Restore order

1. Stop API writes, dispatcher, reaper, maintenance, and all workers. Keep the
   old environment isolated; do not overwrite it as the first recovery action.
2. Provision a clean PostgreSQL target, empty Redis, and an empty/versioned
   object bucket. Point the recovery deployment at those targets.
3. Verify the portable backup before any restore.
4. Run restore with the exact confirmation phrase printed by the command:

```bash
CASE_VIDEO_RESTORE_CONFIRM="RESTORE drill-YYYYMMDD-HHMM" \
  docker compose --profile operations run --rm backup \
  python -m server.app.operations.backup_cli restore \
  /backups/drill-YYYYMMDD-HHMM
```

5. Inspect the JSON report. Require all of the following:
   - expected schema version;
   - zero object-reference errors;
   - zero queue dispatch failures;
   - `rpo_pass=true` and `rto_pass=true` for the drill target;
   - restored running leases are expired and requeued;
   - queued stages appear in the newly empty Redis streams.
6. Start API in read-only operational mode first and inspect jobs, revisions,
   downloads, audit entries, queue age, dead letters, and model readiness.
7. Start dispatcher/reaper, then one worker per queue. Run one no-cost dry-run
   job and one controlled recovery job before enabling normal writes.

The restore command uses the database snapshot's backend: SQLite uses the
consistent backup API; PostgreSQL uses `pg_dump`/`pg_restore`. PostgreSQL restore
cleans the explicitly selected target database, so the exact confirmation and
clean recovery environment are mandatory.

## Failure handling

- Database hash mismatch: quarantine the backup and select another restore
  point. Never recalculate and overwrite the recorded hash.
- Object hash/size mismatch or missing reference: keep service read-only,
  restore the required object version, rerun verification, and record the key
  only in restricted incident evidence.
- Queue dispatch failure: leave writes disabled, repair Redis connectivity,
  and rerun `python -m server.app.workers.control rebuild --once`.
- A stage restored as running must never resume under its old worker lease. If
  it is not reported as expired/requeued, stop worker startup and escalate.
- RPO or RTO miss: record actual timing and data gap, open a Sev 1 release
  blocker, and assign a dated remediation.

## Quarterly evidence

Store the manifest, restore JSON report, timeline, target versions, object
reference result, queue reconstruction result, measured RPO/RTO, duplicate
provider-call check, and operator sign-off under the release evidence recovery
directory. A successful backup without a real restore does not pass `C-DR-01`.
