# Rolling upgrade and rollback runbook

Owner: platform operations. Application engineering approves schema compatibility
and the release image. This procedure is the executable evidence for
`C-UPGRADE-01`.

## Invariants

- Upgrade the API before workers. The API must accept both the currently
  deployed and next message/manifest/schema contract before any new worker is
  started.
- Run migrations as a separate controlled job. Use expand-and-contract: add
  compatible structures first, switch readers/writers later, and remove old
  structures only in a subsequent release.
- Unknown queue message versions go to quarantine. Never guess their schema.
- A job keeps the route, prompt, schema/task registry, and engine image snapshot
  captured when it was created. Normal retry cannot adopt release defaults.
- Application rollback changes code and traffic only. It never restores an old
  database over newer application data and never deletes newly created objects.

## Pre-upgrade capture

Drain no jobs solely for this check. Capture all currently non-terminal jobs
while the old release is still serving traffic:

```bash
docker compose --profile operations run --rm upgrade-capture
```

Copy `/release-evidence/pre-upgrade.json` to immutable release evidence and note
its SHA-256. The snapshot contains no source text or credentials. It records
public route pins, prompt/schema registry pins, engine digest, and immutable
hashes from existing stage/model runs.

Block the release if capture fails, schema readiness is not green, or the
snapshot contains zero jobs when the rehearsal requires an in-flight job.

## Rolling upgrade

1. Verify the new API image against old and new contract fixtures.
2. Run `migration` once. Confirm the old API can still read the expanded schema.
3. Roll API instances and check readiness, error rate, authorization failures,
   queue age, and dead letters.
4. Roll dispatcher/reaper, then one worker queue at a time. Render workers roll
   last because their image digest is part of the job snapshot.
5. Run the immutable snapshot verification:

```bash
docker compose --profile operations run --rm upgrade-verify
```

The command exits `2` on any mismatch. Require `passed=true`, zero issues, and
the expected number of checked jobs. New model runs are compared with each
job's captured task registry, so a new worker using current release defaults is
also rejected.

## Application rollback rehearsal

1. Keep the expanded database and all object data in place.
2. Roll API and workers back to the prior compatible image. Do not run a reverse
   destructive migration.
3. Repeat `upgrade-verify` against the same pre-upgrade snapshot.
4. Resume one controlled in-flight job and ensure queue delivery remains
   idempotent. Confirm there is no duplicate provider call or paid artifact.

If the prior image cannot read the expanded schema, stop the rollback and ship
a forward-fix image. Database restore is a disaster-recovery action, not an
application rollback mechanism.

## Failure handling and evidence

- A changed job snapshot, missing prior stage/model record, or unpinned new
  model run is a release blocker. Stop worker rollout before retrying anything.
- Unknown message versions must remain quarantined until a compatible worker is
  deployed or an explicit converter is reviewed.
- Preserve `pre-upgrade.json`, upgrade verification JSON, rollback verification
  JSON, migration logs, image digests, queue/DLQ graphs, and operator sign-off.
- Reports contain changed field paths and expected/actual digests, not raw
  values. Do not add `.env`, provider keys, source text, or signed URLs to the
  evidence bundle.
