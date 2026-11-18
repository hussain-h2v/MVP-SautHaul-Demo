# SetuHaul Dock Scheduling Platform

An enterprise platform for managing inbound truck arrivals at warehouse docks. Drivers report delays over WhatsApp; coordinators, facility planners, carriers and admins work in four role-based web portals.

> **The one rule:** AI explains and classifies, but **never decides capacity**. Only the deterministic scheduling and booking services create, change or release a slot, and PostgreSQL constraints make a double booking impossible (see [docs/INTEGRITY_PROOF.md](docs/INTEGRITY_PROOF.md)).

---

## Contents

1. [What is in the box](#1-what-is-in-the-box)
2. [Prerequisites](#2-prerequisites)
3. [First-time setup](#3-first-time-setup)
4. [Running the application](#4-running-the-application)
5. [URLs and ports](#5-urls-and-ports)
6. [Demo logins](#6-demo-logins)
7. [Roles and the permission matrix](#7-roles-and-the-permission-matrix)
8. [The four portals](#8-the-four-portals)
9. [WhatsApp driver assistant](#9-whatsapp-driver-assistant)
10. [AI platform](#10-ai-platform)
11. [A typical day: end-to-end walkthrough](#11-a-typical-day-end-to-end-walkthrough)
12. [Testing](#12-testing)
13. [Configuration (.env)](#13-configuration-env)
14. [Project layout and architecture](#14-project-layout-and-architecture)
15. [Troubleshooting](#15-troubleshooting)
16. [Project status](#16-project-status)
17. [Further documentation](#17-further-documentation)

---

## 1. What is in the box

| Part | Technology | Purpose |
|---|---|---|
| `backend` | FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2 | REST API, scheduling and booking engine, AI router, WhatsApp channel, driver agent |
| `frontend` | Next.js 15 (App Router), Tailwind v4, next-intl, TanStack Query | Four portals, English and Hindi, light/dark theme, live updates (SSE) |
| PostgreSQL 16 | partial unique indexes, `tstzrange` EXCLUDE, CHECKs, append-only audit trigger | Source of truth; integrity enforced in the database |
| Redis 7 | rate limits, soft locks, circuit-breaker state, SSE streams, idempotency cache | Fast shared state |
| `worker` | arq | Slot-hold sweeper, notification outbox, WhatsApp delivery, AI log retention |
| `infra` | Docker Compose | Postgres, Redis, API, worker, web |

The old Streamlit/SQLite prototype (`src/`, `tests/`, `scenarios/`, `sql/audit/`, `data/`) is kept for reference only. Its original README is in [docs/LEGACY_PROTOTYPE.md](docs/LEGACY_PROTOTYPE.md).

---

## 2. Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker Desktop | recent, with Compose v2 | **The supported toolchain.** Backend runs on Python 3.12 inside the image, so local Python is not needed. |
| Node.js | 20 or newer | Only if you run the frontend outside Docker (`npm run dev`) |
| Git | any | |

Windows users: run the commands in Git Bash or PowerShell. The seed command needs `MSYS_NO_PATHCONV=1` in Git Bash (shown below).

---

## 3. First-time setup

Run everything from the repository root.

### Step 1: create the environment file

```bash
cp .env.example .env
```

The defaults work for local development. For anything shared, change `JWT_SECRET` and `PROVIDER_KEY_ENCRYPTION_KEY` (32 random bytes, base64). Never commit `.env`.

### Step 2: start PostgreSQL and Redis

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis
```

### Step 3: build the API image and create the schema

```bash
docker compose -f infra/docker-compose.yml build api
docker compose -f infra/docker-compose.yml run --rm api alembic upgrade head
```

This applies every migration (`backend/alembic/versions`, `0001` to `0012`): reference schema, integrity constraints, identity and audit, admin core, docks, booking engine, carrier portal, notifications, coordinator desk, AI platform, WhatsApp channel.

### Step 4: load the reference data

Loads facilities, carriers, drivers, vehicles, docks, slots, shipments and appointments from the SQLite snapshot in `data/`. Demo data is dated **4 August 2026**.

```bash
MSYS_NO_PATHCONV=1 docker compose -f infra/docker-compose.yml run --rm -v "$(pwd -W)/data:/data:ro" api python -m scripts.seed_reference
```

PowerShell equivalent:

```powershell
docker compose -f infra/docker-compose.yml run --rm -v "${PWD}/data:/data:ro" api python -m scripts.seed_reference
```

### Step 5: create the demo users (one per role)

```bash
docker compose -f infra/docker-compose.yml run --rm api python -m scripts.seed_demo_users
```

### Step 6: seed the offline AI provider

Creates a built-in **mock** provider, models, routes and prompts so every AI feature, including the WhatsApp assistant, works without any account or API key. It is safe to re-run.

```bash
docker compose -f infra/docker-compose.yml run --rm api python -m scripts.seed_ai_demo
```

### Step 7: install frontend dependencies (only for non-Docker frontend)

```bash
cd frontend
npm install --legacy-peer-deps
```

---

## 4. Running the application

### Option A: everything in Docker

```bash
docker compose -f infra/docker-compose.yml up -d
```

Starts `postgres`, `redis`, `api`, `worker` and `web`. Open <http://localhost:2000>.

### Option B: backend in Docker, frontend with hot reload (recommended for development)

```bash
docker compose -f infra/docker-compose.yml up -d postgres redis api worker
cd frontend && npm run dev
```

### Useful commands

| Task | Command |
|---|---|
| Follow API logs | `docker compose -f infra/docker-compose.yml logs -f api` |
| Follow worker logs | `docker compose -f infra/docker-compose.yml logs -f worker` |
| Stop everything | `docker compose -f infra/docker-compose.yml down` |
| Stop and **wipe the database** | `docker compose -f infra/docker-compose.yml down -v` |
| Apply new migrations | `docker compose -f infra/docker-compose.yml run --rm api alembic upgrade head` |
| Rebuild after changing `requirements.txt` | `docker compose -f infra/docker-compose.yml build api worker` |
| Re-run the concurrency proof | `docker compose -f infra/docker-compose.yml run --rm api python -m scripts.integrity_proof` |

> Keep the **worker** running. It turns booking events into notifications, expires slot holds, and delivers WhatsApp messages. Without it the portals work but nothing is delivered and holds never expire.

---

## 5. URLs and ports

| Service | URL / port | What it is |
|---|---|---|
| Web (all four portals) | <http://localhost:2000> | Log in once; you are redirected to your role's portal |
| API | <http://localhost:8000> | FastAPI service |
| API docs (Swagger) | <http://localhost:8000/docs> | Interactive OpenAPI explorer |
| OpenAPI JSON | <http://localhost:8000/openapi.json> | Schema used for the typed client |
| Metrics | <http://localhost:8000/metrics> | Prometheus metrics |
| WhatsApp webhook | `http://localhost:8000/webhooks/whatsapp` | GET verifies, POST receives (signed with `X-Hub-Signature-256`) |
| PostgreSQL | `localhost:5432` | database `setuhaul`, user `setuhaul` |
| Redis | `localhost:6379` | |

Portal entry points (after login):

| Portal | Path | Intended for |
|---|---|---|
| Admin | <http://localhost:2000/admin> | Head office |
| Facility | <http://localhost:2000/facility> | Warehouse planners |
| Coordinator | <http://localhost:2000/coordinator> | Operations desk |
| Carrier | <http://localhost:2000/carrier> | Transport companies |

The login page is <http://localhost:2000/login>. Each user can only open their own portal; other portals redirect back.

---

## 6. Demo logins

Password for all demo users: `SetuHaul-Demo-2026` (demo only; change or remove outside development).

| Email | Role | Portal | Scope |
|---|---|---|---|
| `admin@setuhaul.demo` | admin | `/admin` | Whole network |
| `planner@setuhaul.demo` | facility_planner | `/facility` | One facility (the Gurgaon facility) |
| `coordinator@setuhaul.demo` | coordinator | `/coordinator` | All facilities |
| `carrier@setuhaul.demo` | carrier_user | `/carrier` | One carrier's own data only |

Accounts lock after repeated wrong passwords. New users are invited by an admin (Admin, Users) and set their own password at `/accept-invite`.

---

## 7. Roles and the permission matrix

Access is enforced twice: by the **capability matrix** (what you may do) and by **scope** (which rows you may see). Scope is applied in the repository layer, so a carrier can never read another carrier's data and a planner can never read another facility's. Menus in the UI are filtered by capability, but the API enforces the rules independently.

`W` = read and write, `R` = read only, `-` = no access.

| Capability | Admin | Facility planner | Coordinator | Carrier user |
|---|:-:|:-:|:-:|:-:|
| Manage master data (facilities, carriers, users) | W | - | - | - |
| Create/edit/offer/cancel shipments | W | - | - | - |
| Docks, slots and rules | R | **W** | R | - |
| Day schedule | R | **W** | R | R |
| Drivers and vehicles | R | - | R | **W** |
| Assign driver and vehicle to a shipment | - | - | - | **W** |
| Shipment details | R | R | R | R |
| Booking decisions (approve, suggest, hold, reject) | - | R | **W** | - |
| Escalations and conversation takeover | - | - | **W** | - |
| AI management (providers, keys, prompts, budgets) | **W** | - | - | - |
| AI insights | R | R | **W** | R |
| Analytics and reports | R | R | R | R |
| Audit log | R | - | R | - |
| System settings | **W** | - | - | - |

The matrix lives in `backend/app/core/permissions.py` and is tested cell by cell in `backend/tests/test_permission_matrix.py`.

---

## 8. The four portals

All portals share the same shell: capability-based sidebar, language switch (English / Hindi), light/dark theme, a live-connection dot (server-sent events), notification bell, keyboard-accessible skip link, and a mobile sidebar.

### 8.1 Admin portal `/admin`: head office

Sets up the network and governs the AI and WhatsApp systems.

| Screen | What you can do |
|---|---|
| **Dashboard** | Network totals (live). Network KPIs arrive with Milestone 9. |
| **Facilities** `/admin/facilities` | Create/edit facilities, working hours, timezone, rules, contacts (missing-email flag); CSV import (dry-run, atomic) and export; search, sort, filter. |
| **Carriers** `/admin/carriers` | Create/edit carriers, allowed vehicle types, fleet counts and shipment statistics. |
| **Users** `/admin/users` | Invite users, assign role plus facility or carrier scope, disable, force logout, view and revoke sessions. |
| **Drivers** `/admin/drivers` | Directory across carriers, WhatsApp verification status, history, CSV export. |
| **Shipments** `/admin/shipments` | Create, edit, offer to a carrier, cancel; timeline per shipment; CSV import/export. Carriers never see drafts. |
| **AI** `/admin/ai` | Providers, API keys (encrypted at rest, key pools), models, routes and fallback chains, versioned prompts, evaluations (golden set), usage and cost, budgets and alerts, safety settings and kill switch, request logs. See [section 10](#10-ai-platform). |
| **WhatsApp** `/admin/whatsapp` | Overview and webhook status, **simulator** (phone-style chat), message templates (en/hi/te), delivery failures, message log, opt-ins and opt-outs. See [section 9](#9-whatsapp-driver-assistant). |
| **Audit** `/admin/audit` | Filterable, append-only log of every write: who, what, when, from where, with trace id. |
| **Settings** `/admin/settings` | Hold and confirmation TTLs, ranking weights, languages, grace periods, coordinator phone. |
| **Notifications** | Alerts such as AI provider failures, budget thresholds and WhatsApp delivery failures. |

### 8.2 Facility portal `/facility`: warehouse planners

Owns the physical capacity of **one facility**: docks, slots and the daily schedule.

| Screen | What you can do |
|---|---|
| **Home** | Today at a glance for your facility. |
| **Schedule** `/facility/schedule` | Live day-schedule grid (docks by time). Open a slot, drag-move or re-book an appointment, suggest another slot, cancel. |
| **Pending** `/facility/pending` | Appointments waiting for planner confirmation (late-evening starts) with confirm or reject. |
| **Docks** `/facility/docks` | Create, edit and retire docks (standard, reefer, heavy); capability flags. |
| **Slots** `/facility/slots` | Generate slots (dry run, overlap-safe), bulk block or open with a preview of affected bookings, copy a day. |
| **Events** `/facility/events` | Dock breakdowns, maintenance and capacity changes, with a preview of affected bookings before you save. Affected bookings go to re-planning. |
| **Rules** `/facility/rules` | Facility rules with effective dates and change history. |
| **Inbound** `/facility/inbound` | Trucks expected today with their effective ETA and confidence. |
| **Yard and gate** `/facility/yard` | Check-in, dock assignment, unloading and departure lifecycle; no-show marking. |
| **Contacts** `/facility/contacts` | Gate supervisor and other contacts shared with drivers. |
| **Reports** `/facility/reports` | Utilisation and throughput. |

### 8.3 Coordinator portal `/coordinator`: operations desk

Handles the exceptions that need a human. Coordinators **decide**; the engine only recommends.

| Screen | What you can do |
|---|---|
| **Inbox** `/coordinator` | Live queue of driver slot requests. Soft locks show who else is looking at a request. Open one to see the ranked options with plain-language explanations, then **approve, suggest another slot, keep on hold, reject, or escalate**, with message templates for the driver. |
| **Competing** | When requests fight over the same slot: ranking by priority and rules, with a mandatory reason to override. |
| **Holds** | Active slot holds with extend and release. |
| **Escalations** | Cases the assistant could not resolve (safety, disputes, no feasible slot, low confidence, driver declined) with the full hand-off: transcript, ETA, shipment, reason. |
| **Conversations** | Read any driver thread, **take over** from the bot, reply, then hand back. Replies go out through WhatsApp. |
| **Board** | Live dock board. |
| **Handover** | Shift handover summary (open requests, holds, escalations). |
| **Insights** | AI-generated summaries (Milestone 9). |
| **Activity** | Your own audit trail. |

### 8.4 Carrier portal `/carrier`: transport companies

Carriers see **only their own** shipments, drivers and vehicles.

| Screen | What you can do |
|---|---|
| **Dashboard** | Open offers, assignments needed, upcoming arrivals. |
| **Incoming shipments** `/carrier/shipments` | Accept or decline offers; assign a driver and vehicle (incompatible vehicles are blocked, risky ones warned); reassign with a reason. |
| **Drivers** `/carrier/drivers` | Create/edit drivers, CSV import/export, start **WhatsApp verification** (a one-time code is sent to the driver). |
| **Vehicles** `/carrier/vehicles` | Fleet CRUD and CSV; heavy and reefer capability. |
| **Tracker** `/carrier/tracker` | Read-only status of every shipment: ETA, slot, appointment state. |
| **Slot changes** `/carrier/slot-changes` | Feed of slot moves, holds, rejections and re-plans affecting your shipments. |
| **Notifications** | Offers, confirmations, expiring holds, stale ETAs. |
| **Insights / Reports** | Carrier-level KPIs (insights arrive with Milestone 9). |

---

## 9. WhatsApp driver assistant

Drivers talk to a WhatsApp assistant (LangGraph agent) in **English, Hindi or Telugu** (Hinglish text gets a reply in the driver's preferred language).

**What it does:** collects a delay report (how late, why, when the unload can finish), records the declared ETA, shows feasible slot options, and, if the driver picks one, places a **hold** and creates a **request for the coordinator**. It also answers status and gate-contact questions and records "I have arrived".

**What it never does:**
- It never confirms a slot. Only a coordinator (or the driver accepting a coordinator's suggestion, executed by the booking service) can.
- It never trusts identity from message text; the driver is the verified WhatsApp number.
- It never lets a model write replies about capacity. All reply text comes from reviewed catalogue strings; times and docks are inserted by code.
- It escalates immediately, without any model, on safety words (accident, fire, medical, robbery; replies with 112), disputes and penalties, and prompt-injection attempts.
- If AI is switched off or down, fixed menus and buttons still work.

### Try it without a WhatsApp account (simulator)

1. Make sure the worker is running and Step 6 of setup is done.
2. Log in as admin and open <http://localhost:2000/admin/whatsapp/simulator>.
3. Choose a driver (their number must be verified and opted in) and chat. Tap buttons and list rows as a driver would. Messages appear on the coordinator's Conversations screen.

Or from the command line:

```bash
docker compose -f infra/docker-compose.yml run --rm api python -m scripts.wa_simulator --number +919876543210 "Truck breakdown, 2 hours late"
docker compose -f infra/docker-compose.yml run --rm api python -m scripts.wa_simulator --number +919876543210 --button delay:total
```

(Use the base URL `--base-url http://api:8000` when running inside Compose if the default does not resolve.)

### Connect real WhatsApp (production)

Set `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID` from the Meta developer console, point the webhook at `https://<your-host>/webhooks/whatsapp`, and submit the templates listed in Admin, WhatsApp, Templates for approval. Hindi and Telugu strings are drafts and need native-speaker review before go-live.

---

## 10. AI platform

All model calls go through one function, `ai.run`, inside `backend/app/modules/ai`. Provider SDKs (via LiteLLM) are not imported anywhere else.

- **Fallback chains** per task, with circuit breakers (state in Redis) and key pools.
- **Budgets and alerts**, per-provider and global; admins are notified at thresholds.
- **PII masking** before any prompt leaves the system; **kill switch** per task or globally.
- **Graceful degradation**: when AI is unavailable the caller gets a deterministic fallback, never an error page.
- **Versioned prompts** and an **evaluation golden set** you can run from Admin, AI, Evals.
- **Offline mock provider** (kind `mock`), seeded by `scripts.seed_ai_demo`, so the whole system runs with no keys.

To use a real model: Admin, AI, Providers (add provider), Keys (add key; stored AES-GCM encrypted), Models, then Routes (point a task at your model and set a fallback). The agent only uses AI for intent classification and extraction; AI code never writes to the database.

---

## 11. A typical day: end-to-end walkthrough

Use four browser windows (or profiles), one per role.

1. **Admin** creates a shipment and **offers** it to a carrier (`/admin/shipments`).
2. **Carrier** accepts, then assigns a driver and vehicle (`/carrier/shipments`). The driver is verified over WhatsApp.
3. **Planner** has generated slots and sees the appointment on the grid (`/facility/schedule`).
4. The driver is running late and messages the bot (simulator, section 9). The bot asks how late and why, records the ETA, lists slot options, and on choosing one places a **hold**. Nothing is confirmed.
5. **Coordinator** sees the request appear live in the inbox, reviews the ranked options and approves, suggests another slot, or rejects.
6. The driver is told the outcome. **Carrier** sees it under Slot changes. **Planner** sees the new booking on the grid.
7. If nobody answers, the hold expires and the worker's sweeper frees the slot. Everything is in the **Audit** log.

---

## 12. Testing

Always use a private database suffix so test runs do not collide with each other or your dev data.

```bash
# Backend: full suite
docker compose -f infra/docker-compose.yml run --rm -e TEST_DB_SUFFIX=_all api pytest -q -p no:cacheprovider

# Backend: one file
docker compose -f infra/docker-compose.yml run --rm -e TEST_DB_SUFFIX=_me api pytest -q -p no:cacheprovider tests/test_m8_agent.py

# Frontend
cd frontend
npm run lint && npx tsc --noEmit && npm test && npm run build
```

Backend tests cover the permission matrix cell by cell, authentication and lockout, scope isolation, audit, SSE, every booking path including concurrent races, the AI router's failure paths, the WhatsApp channel, and the driver agent in three languages.

---

## 13. Configuration (.env)

Copy `.env.example` to `.env`. Notable variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL`, `REDIS_URL` | Connections (defaults match Compose) |
| `JWT_SECRET`, `JWT_ACCESS_TTL_MINUTES`, `JWT_REFRESH_TTL_DAYS` | Session tokens |
| `PROVIDER_KEY_ENCRYPTION_KEY` | AES-GCM key protecting stored AI provider keys |
| `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | Webhook signature and verification (dev values provided for the simulator) |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Real WhatsApp Cloud API; blank means simulator only |
| `CORS_ORIGINS` | Allowed web origins (default `http://localhost:2000`) |
| `DEFAULT_TIMEZONE` | Display timezone, `Asia/Kolkata` (storage is always UTC) |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-visible API URL |
| `SENTRY_DSN`, `LANGSMITH_TRACING` | Optional observability |

Operational settings (hold TTL, ranking weights, coordinator phone and so on) are changed in the UI at Admin, Settings, not in `.env`.

---

## 14. Project layout and architecture

```
backend/
  app/core/            config, db, security, permissions, scope, audit, events, idempotency, metrics
  app/modules/<name>/  router.py, service.py, repository.py, schemas.py, models.py
  app/workers/         arq worker and cron jobs
  alembic/versions/    migrations 0001 to 0012
  scripts/             seed_reference, seed_demo_users, seed_ai_demo, integrity_proof, wa_simulator
  tests/
frontend/
  app/                 (auth) login, accept-invite; admin, facility, coordinator, carrier
  components/ lib/     UI primitives, API client, auth, SSE, portal navigation
  messages/            en.json, hi.json
infra/                 Dockerfiles and docker-compose.yml
docs/                  PLAN, DECISIONS, DATA_AUDIT, INTEGRITY_PROOF, LEGACY_PROTOTYPE
```

Engineering rules:

1. Business logic lives in **services**; routers validate, authorise and call services. A module reads another module's data only through that module's service. No cross-module ORM relationships.
2. **AI never writes to the database.** It calls typed tools that call services. Provider SDKs live only in `modules/ai`.
3. **Integrity is enforced in PostgreSQL**: one active claim per slot, time-range exclusion, CHECK constraints, append-only audit.
4. Every mutable table has a UUID `id`, `created_at`, `updated_at` and `version`.
5. `timestamptz` everywhere, UTC storage, display in Asia/Kolkata. No secrets in code.
6. Strict typing (mypy strict, TypeScript strict), ruff and prettier.

Booking flow in brief: `place_hold` locks the slots in id order, creates a hold (15 minutes) and a claim; an approval turns the hold into an appointment; the sweeper expires stale holds. Events go through a transactional outbox to in-app notifications, WhatsApp delivery and live SSE updates.

---

## 15. Troubleshooting

| Symptom | Fix |
|---|---|
| `docker compose` cannot connect | Start Docker Desktop and wait until it reports running. |
| API fails on start with a missing table or column | Run `alembic upgrade head` (setup step 3). |
| Login works but lists are empty | Run the seed commands (steps 4 to 6). |
| Port 2000, 8000, 5432 or 6379 already in use | Stop the other process, or change the host port in `infra/docker-compose.yml`. |
| Notifications, WhatsApp messages or hold expiry never happen | The worker is not running: `docker compose -f infra/docker-compose.yml up -d worker`. |
| Seed script cannot find `/data` on Windows Git Bash | Prefix with `MSYS_NO_PATHCONV=1`, or use the PowerShell form. |
| Frontend install peer-dependency errors | Use `npm install --legacy-peer-deps`. |
| AI features say "unavailable" | Run `scripts.seed_ai_demo`, and check Admin, AI, Safety that the kill switch is off. |
| Need a clean slate | `docker compose -f infra/docker-compose.yml down -v`, then repeat setup. |

---

## 16. Project status

| Milestone | Scope | State |
|---|---|---|
| 0 Foundation | Repo, Compose, schema, seed | Done |
| 1 Identity and shell | Auth, RBAC, audit, settings, SSE, shell | Done |
| 2 Admin core | Facilities, carriers, drivers, shipments | Done |
| 3 Facility portal | Docks, slots, rules, schedule, yard | Done |
| 4 Scheduling and booking | Options, holds, approvals, sweeper, integrity proof | Done |
| 5 Carrier portal | Fleet, assignment, tracker, notifications | Done |
| 6 Coordinator portal | Inbox, decisions, escalations, takeover | Done |
| 7 AI platform | Router, fallback, budgets, prompts, evals | Done |
| 8 WhatsApp and agent | Webhook, templates, simulator, LangGraph assistant | In progress (agent and admin screens built and tested; final integration and commit pending) |
| 9 Insights and optimiser | KPIs, AI insights, optional optimiser | Planned |
| 10 Hardening and delivery | Load tests, end-to-end journeys, security review, runbook | Planned |

Known limits: ETAs are driver-declared (no live GPS); Hindi and Telugu strings need native review; TOTP, password-reset email and email delivery are deferred (invite tokens are returned by the API in development); no real AI provider has been called yet (offline mock only).

---

## 17. Further documentation

- [docs/PLAN.md](docs/PLAN.md): milestone plan and status
- [docs/DECISIONS.md](docs/DECISIONS.md): numbered architecture decisions
- [docs/DATA_AUDIT.md](docs/DATA_AUDIT.md): audit of the source data
- [docs/INTEGRITY_PROOF.md](docs/INTEGRITY_PROOF.md): concurrency proof of zero double bookings
- [backend/README.md](backend/README.md): backend module map
- [frontend/README.md](frontend/README.md): frontend screen map
- [docs/LEGACY_PROTOTYPE.md](docs/LEGACY_PROTOTYPE.md): the original Streamlit/SQLite prototype
- Live API reference: <http://localhost:8000/docs>
