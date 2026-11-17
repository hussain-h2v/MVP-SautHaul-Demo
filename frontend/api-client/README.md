# @setuhaul/api-client

TypeScript types generated from the FastAPI OpenAPI schema.

`npm run generate` reads `backend/openapi.json` and writes `schema.d.ts`. That spec file is not exported yet,
so `frontend/lib/api.ts` and `frontend/lib/types.ts` use hand-written types for now. Once the API exports its
schema, switch the web app to the generated types and add a CI check that regeneration produces no diff.
