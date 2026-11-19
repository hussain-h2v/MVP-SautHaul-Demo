#!/usr/bin/env bash
# Deploy/update the demo stack on the EC2 host. Run from anywhere inside the repo.
# Usage: ./infra/deploy.sh [--seed]   (--seed loads reference data + demo users; first deploy only)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo ".env missing - copy .env.production.example to .env and fill it in"; exit 1; }
grep -q '^JWT_SECRET=change-me' .env && { echo "Set real secrets in .env first"; exit 1; }

DC="docker compose -f infra/docker-compose.prod.yml --env-file .env"
git pull --ff-only || true
$DC build
$DC up -d postgres redis
$DC run --rm api alembic upgrade head
if [ "${1:-}" = "--seed" ]; then
  $DC run --rm -v "$(pwd)/data:/data:ro" api python -m scripts.seed_reference
  $DC run --rm api python -m scripts.seed_demo_users
fi
$DC up -d
$DC ps
echo "Done: https://$(grep '^SITE_ADDRESS=' .env | cut -d= -f2)"
