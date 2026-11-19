# AWS demo deployment (single EC2 + docker compose)

1. **EC2**: Ubuntu 24.04, `t3.medium`, 30 GB gp3, Elastic IP, region `ap-south-1`.
   Security group: 80/443 from anywhere, 22 from your IP only.
2. **Hostname**: your domain's A record -> Elastic IP, or `<ip-with-dashes>.sslip.io` (e.g. `13-232-1-2.sslip.io`).
3. **Install**: `sudo apt update && sudo apt install -y docker.io docker-compose-v2 git && sudo usermod -aG docker $USER` (re-login).
4. **Clone & configure**: `git clone <repo> && cd MVP-SautHaul-Demo && cp .env.production.example .env`, then fill in
   `SITE_ADDRESS`, `POSTGRES_PASSWORD`, `JWT_SECRET`, `PROVIDER_KEY_ENCRYPTION_KEY`, `CORS_ORIGINS`, `DEMO_PASSWORD`.
5. **First deploy**: `./infra/deploy.sh --seed`. Later updates: `./infra/deploy.sh`.
6. **Log in** at `https://<SITE_ADDRESS>` as `admin@setuhaul.demo` / `coordinator@setuhaul.demo` /
   `planner@setuhaul.demo` / `carrier@setuhaul.demo` with `DEMO_PASSWORD`.
7. **WhatsApp (optional)**: Meta webhook URL `https://<SITE_ADDRESS>/webhooks/whatsapp` + `WHATSAPP_VERIFY_TOKEN`.

Ops: logs `docker compose -f infra/docker-compose.prod.yml logs -f api worker`;
backup `docker compose -f infra/docker-compose.prod.yml exec postgres pg_dump -U setuhaul setuhaul > backup.sql`.
Stop the instance between demos to save cost (the Elastic IP keeps the address).
