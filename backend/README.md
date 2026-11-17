# SetuHaul backend (FastAPI modular monolith)

Python 3.12, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL 16, Redis, arq. Capacity decisions are deterministic code only; AI never writes to the DB.

Run everything through Docker (see root `CLAUDE.md`). Status: done = tested, planned = milestone number from `docs/PLAN.md`.

## Functionality map

| Module (`app/modules/…`) | Functionality | Status |
|---|---|---|
| `auth` | Login/logout/refresh (rotating refresh tokens), httpOnly cookies, CSRF, account lock, rate limit, invite accept, change password, session list/revoke, RBAC dependency `require(cap, level)`, SSE stream `/events/stream` | done (M1) |
| `users` | Invite users, set role + facility/carrier scope, disable, force logout | done (M1) |
| `settings` | System settings (TTLs, ranking weights, languages, grace) read/update with audit | done (M1) |
| `audit` | Append-only audit log (DB trigger), automatic capture of every write with actor/IP/trace, filterable API | done (M1) |
| `facilities`, `carriers`, `drivers`, `shipments` | Scope-filtered paginated lists (repository-level scoping) | read done (M1); create/edit/CSV/timeline M2, M5 |
| `vehicles` | Vehicle types and vehicles (models, seeded) | models done; API M5 |
| `docks`, `slots` | Docks, dock events, slot generator, block/open | models done; API M3 |
| `appointments` | Appointments, check-ins, yard/gate | models done; API M3/M4 |
| `eta` | ETA history and effective-ETA precedence | models done; logic M4 |
| `scheduling` | `find_options` feasibility + ranking (read-only) | M4 |
| `booking` | Holds, approve/suggest/reject, expiry sweeper, cancel/no-show, concurrency-safe | M4 |
| `exceptions` | Driver exception workflow, escalations | models done; API M6 |
| `notifications` | In-app/email notifications, outbox | M6 |
| `whatsapp`, `agent` | Webhook, templates, simulator, LangGraph driver assistant | M8 |
| `ai` | Providers, keys, models, routes, fallback, circuit breakers, budgets, prompts, evals | M7 |
| `insights`, `analytics` | Driver/dock/coordinator/carrier/network insights, dashboards | M9 |

## Cross-cutting (`app/core`)
`config`, `db` (UUID/version mixins), `security` (argon2, JWT, AES-GCM), `permissions` (capability matrix), `scope` (row-level filters), `audit_events` (session hook), `events` (Redis Streams SSE fan-out), `idempotency`, `errors`, `logging` (structlog JSON + trace id), `context`.

## Data
Migrations `alembic/versions` (0001 reference schema, 0002 integrity constraints + views, 0003 identity/audit/settings). Seed: `scripts/seed_reference.py` (SQLite snapshot), `scripts/seed_demo_users.py` (one demo user per role).

## Tests
`pytest` runs against a throwaway `setuhaul_test` database migrated from scratch: 137 tests (permission matrix cell-by-cell, auth/lockout/CSRF/rotation, scope isolation, audit, SSE isolation).
