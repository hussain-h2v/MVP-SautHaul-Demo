# SetuHaul frontend (Next.js App Router)

Four role-based portals in one app, English + Hindi (next-intl, cookie locale), light/dark theme, accessible (WCAG AA goals), live updates over SSE. Talks to the backend through the `/api` rewrite (`API_INTERNAL_URL`, default `http://localhost:8000`).

```bash
cd frontend && npm install --legacy-peer-deps && npm run dev     # http://localhost:3000
npm run lint && npx tsc --noEmit && npm test && npm run build
```
Demo logins (password `SetuHaul-Demo-2026`): `admin@`, `planner@`, `coordinator@`, `carrier@` `setuhaul.demo`.

## Functionality map

| Area | Screens / features | Status |
|---|---|---|
| Shell | Login, role redirect, route guard, capability-based menus, user menu, language + theme switch, live-status dot (SSE), mobile sidebar, skip link | done (M1) |
| **Admin** `/admin` | Network dashboard | M9 |
| | Facilities, Carriers, Users and roles, Drivers directory, Shipments (+timeline, CSV) | M2 |
| | AI management (providers, keys, models, routes, prompts, evals, usage, budgets, logs, kill switch) | M7 |
| | WhatsApp management + simulator | M8 |
| | Audit log, System settings, System health, Reports | M2/M10 |
| **Facility** `/facility` | Facility selector + home, Day schedule grid (live, drag to move), Pending confirmations | M3 |
| | Docks, Slot generator/manager, Dock events, Facility rules | M3 |
| | Inbound trucks, Yard and gate, Contacts, Insights, Reports | M3/M9 |
| **Coordinator** `/coordinator` | Live inbox, Request detail with ranked options, Approve/Suggest/Hold/Reject/Escalate | M6 |
| | Competing requests, Holds, Escalations, Conversation viewer (takeover), Live board, Shift handover, Insights | M6/M9 |
| **Carrier** `/carrier` | Dashboard, Incoming shipments (accept/decline), Assign driver + vehicle | M5 |
| | Drivers, Vehicles (CSV), Read-only shipment tracker, Slot changes, Notifications, Insights, Reports | M5/M9 |

Source layout: `app/<portal>/…` routes, `components/` (shell, ui primitives), `lib/` (api client, auth, sse, portals/nav), `messages/{en,hi}.json`, `api-client/` (OpenAPI types, generated from `backend/openapi.json` once exported).
