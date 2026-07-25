# Case Video Server

This server wraps the existing `scripts/case-video` pipeline behind a deployable FastAPI API and a Redis-backed worker.

## Current Scope

- Create jobs from a project directory under `CASE_VIDEO_SEED_PROJECTS_ROOT` or an uploaded `.zip`.
- Persist `job_manifest.json`, `events.jsonl`, `model_runs.jsonl`, logs, project files, QA files and final media under `CASE_VIDEO_DATA_ROOT`.
- Expose job status, events, artifacts, cancel, retry and health endpoints.
- Run the existing CLI from the worker. Rendering remains serialized by the current Remotion lock.
- Keep model routing fixed on the server:
  - title/narration: Azure Claude deployment `salesnail-cs-46`, sent only through the Azure Anthropic Messages endpoint with `model=salesnail-cs-46`
  - Remotion/storyboard/Visual Beat planning: the same Azure Anthropic Claude route
  - other text/reasoning tasks: OpenAI Responses API with `gpt-5.5`

The repository root `.env` already supplies `AZURE_ANTHROPIC_ENDPOINT`, `AZURE_ANTHROPIC_API_KEY`, and `AZURE_ANTHROPIC_VERSION`. The server pins the Azure deployment to `salesnail-cs-46`; `CASE_VIDEO_AZURE_ANTHROPIC_ENDPOINT`, `CASE_VIDEO_AZURE_ANTHROPIC_API_KEY`, and `CASE_VIDEO_AZURE_ANTHROPIC_VERSION` may override connection settings. Secrets and endpoint URLs are never returned by the API or written to model-run records.

The worker supports `CASE_VIDEO_DRY_RUN=1` for deployment and API acceptance without calling paid model, TTS, image or render services.

Phase B/B1 is also implemented: manifest v2, versioned prompt/schema contracts, a fixed task registry, strict route snapshots, bounded same-model structure repair, and stable public error payloads. Source ingestion, review revisions/UI, the full source-to-video pipeline, and Phase C distributed persistence remain under active development; see `docs/acceptance/server-b-c-status.md` for evidence-backed status.

## Local Run

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-server.txt
CASE_VIDEO_DRY_RUN=1 CASE_VIDEO_REDIS_URL=redis://localhost:6379/0 uvicorn server.app.main:create_app --factory --reload
CASE_VIDEO_DRY_RUN=1 python -m server.app.workers.worker
```

Create a dry-run job from an existing project:

```bash
curl -X POST http://localhost:8000/v1/jobs \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: demo-001' \
  -d '{"project_name":"demo","seed_project":"sales_management_case04_video","approval_mode":"editorial"}'
```

## Docker Compose

```bash
cp server/.env.example server/.env.local
COMPOSE_DISABLE_ENV_FILE=1 docker compose --env-file server/.env.local up --build
```

Use `CASE_VIDEO_API_TOKEN` before exposing the service outside a trusted network. Do not commit local env files.

This repository's historical root `.env` is not guaranteed to be Docker-Compose-compatible; use `COMPOSE_DISABLE_ENV_FILE=1` so Compose reads only the explicit env file you pass.
