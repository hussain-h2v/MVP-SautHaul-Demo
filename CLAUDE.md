# SetuHaul Dock Scheduling Platform

Enterprise platform: drivers report delays via WhatsApp; coordinators, facility planners, carriers and admins work in four Next.js portals; AI explains/classifies but **never decides capacity**. Only the scheduling and booking services create, change or release a slot.

The legacy Streamlit/SQLite prototype lives in `src/`, `tests/`, `scenarios/`, `sql/audit/`, `data/` and is kept as reference. New work goes in `backend/`, `frontend/`, `infra/`.

## Layout
- `backend` FastAPI modular monolith (`app/core`, `app/modules/<name>/{router,service,repository,schemas,models}.py`, `app/workers`, `alembic`, `scripts`, `tests`)
- `frontend` Next.js App Router, route groups `(auth) admin facility coordinator carrier`
- `frontend/api-client` TS client generated from the OpenAPI schema
- `infra` Dockerfiles + `docker-compose.yml`; `docs` PLAN, DECISIONS, DATA_AUDIT, etc.

## Rules
1. Business logic in services; routers validate/authorise/call services. A module reads another module's data only via that module's service. No cross-module ORM `relationship()`.
2. AI code never writes to the DB; it calls typed tools -> services. Provider SDKs only inside `modules/ai`.
3. Integrity is enforced in PostgreSQL (partial unique indexes, tstzrange EXCLUDE, CHECKs) - see migration `0002`.
4. Every mutable table: UUID `id`, `created_at`, `updated_at`, `version`. Reference entities keep their business key (e.g. `SHP1002`) as unique `code`.
5. timestamptz everywhere, UTC storage, display Asia/Kolkata. No secrets in code; config from env (`.env.example`).
6. Strict typing (mypy strict, TS strict), ruff + prettier. Tests with code; commit per milestone.

## Commands (Docker is the supported toolchain; local Python is 3.14, target is 3.12)
```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
docker compose -f infra/docker-compose.yml run --rm api alembic upgrade head
MSYS_NO_PATHCONV=1 docker compose -f infra/docker-compose.yml run --rm -v "$(pwd -W)/data:/data:ro" api python -m scripts.seed_reference
docker compose -f infra/docker-compose.yml run --rm api pytest -q
cd frontend && npm run dev
```
