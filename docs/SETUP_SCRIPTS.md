# SETUP_SCRIPTS.md — Setup and Helper Scripts

Project: Smart Observability and AIOps Platform (CICADA 2026)

> **Honest status:** none of the commands or scripts below have been run yet, because the implementation files do not exist at this stage. Treat every command as a design to be verified. When a command is confirmed on a real machine, tick it in section 10. Collector and seed command names are fixed here so all four members use the same ones; implementations must match them.

---

## 1. Prerequisites

| Tool | Version | Check |
|---|---|---|
| Git | any recent | `git --version` |
| Docker + Docker Compose v2 | recent | `docker --version`, `docker compose version` |
| Python | 3.11+ | `python --version` |
| Node.js | 20 LTS+ | `node --version` |
| npm | bundled with Node | `npm --version` |

Docker is the primary path. Section 6 covers running without Docker as a fallback.

## 2. First-Time Setup (everyone)

```bash
git clone <repo-url> smart-observability
cd smart-observability
git checkout integration
git checkout -b feature/<your-workspace>   # use your assigned branch name

cp .env.example .env
```

Generate your own secrets and put them in `.env` (do not commit `.env`):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # JWT_SECRET
python -c "import secrets; print(secrets.token_urlsafe(32))"   # COLLECTOR_TOKEN_HASH_SALT
python -c "import secrets; print(secrets.token_urlsafe(32))"   # PSEUDONYM_SALT
```

Also change `POSTGRES_PASSWORD` and keep it consistent with `DATABASE_URL`.

## 3. Start the Whole Stack (Docker)

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f backend
```

Expected (to verify): `postgres` becomes healthy, then `backend` healthy, then `frontend` up.

| URL | What |
|---|---|
| http://localhost:8000/health | Backend health |
| http://localhost:8000/docs | OpenAPI / Swagger page |
| http://localhost:5173 | Dashboard |

Stop and clean:

```bash
docker compose down              # stop, keep data
docker compose down -v           # stop and DELETE database and collector volumes
```

## 4. Seed Demo Data

`scripts/seed_demo.py` (owned by Member 2) must:
1. Apply migrations if not already applied.
2. Create **Tenant A** and **Tenant B**.
3. Create an admin user per tenant (credentials from `.env` seed variables).
4. Register collectors: two for Tenant A, one for Tenant B.
5. Print each collector's token **once**; only a hash is stored.
6. Never print or log other secrets.

```bash
docker compose exec backend python scripts/seed_demo.py
```

Copy the printed Tenant A collector token into `.env` as `COLLECTOR_TOKEN` and set `COLLECTOR_ID` / `COLLECTOR_TENANT_ID` to the printed values.

## 5. Start a Collector and the Generator

Command names used across all documents (Member 1 implements these):

```bash
# Start collector with generator in normal mode
docker compose --profile collector up -d collector

# Or run locally (no Docker) from collector-security/
python -m collector.cli run --config ../.env

# Generator modes (match DEMO_GUIDE.md)
python -m collector.cli generate --mode normal
python -m collector.cli generate --mode cpu_spike --duration 60
python -m collector.cli generate --mode memory_spike
python -m collector.cli generate --mode latency_spike
python -m collector.cli generate --mode packet_loss
python -m collector.cli generate --mode failed_logins
python -m collector.cli generate --mode sensitive        # fake secrets, for redaction/Egress demo
python -m collector.cli generate --mode out_of_order
python -m collector.cli replay --last 20                 # resend last 20 payloads (duplicate test)

# Inspect local state
python -m collector.cli status                           # queue depth, last send, backoff state
python -m collector.cli audit --last 10                  # egress audit entries
```

If the final CLI differs, update this section and `DEMO_GUIDE.md` together.

## 6. Running Without Docker (Fallback)

Use this if Docker fails at the venue. Needs a local PostgreSQL, or temporarily set `DATABASE_URL` to a local SQLite URL **for development only** if the backend supports it (decision for Member 2 to confirm and document).

### Backend (+ AIOps engine)
```bash
cd backend-database
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e ../aiops-engine
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend
```bash
cd frontend-dashboard
npm install
npm run dev                          # http://localhost:5173
# Mock mode, no backend needed:
VITE_USE_MOCK=true npm run dev       # Windows PowerShell: $env:VITE_USE_MOCK="true"; npm run dev
```

### Collector
```bash
cd collector-security
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m collector.cli run
```

### AIOps engine (standalone tests)
```bash
cd aiops-engine
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

## 7. Per-Member Quick Commands

| Member | Run | Test |
|---|---|---|
| 1 — collector-security | `python -m collector.cli run` | `cd collector-security && pytest -q` |
| 2 — backend-database | `uvicorn app.main:app --reload` | `cd backend-database && pytest -q` |
| 3 — aiops-engine | `pytest -q` in `aiops-engine/` | same |
| 4 — frontend-dashboard | `npm run dev` | `npm test` (or the agreed command) |

Each member can work alone: Member 4 with `VITE_USE_MOCK=true`; Member 3 with synthetic series in tests; Member 1 against a stub endpoint; Member 2 with sample payloads from `sample-data/`.

## 8. Helper Scripts to Create in `scripts/`

| Script | Owner | Purpose |
|---|---|---|
| `scripts/seed_demo.py` | Member 2 | Tenants, users, collectors, tokens (section 4) |
| `scripts/check_env.sh` | Member 2 | Fails if `.env` is missing or still holds placeholder values (`replace-with`, `change-me`) |
| `scripts/outage_drill.sh` | Member 1 | Stops backend, lets collector queue, restarts, compares counts |
| `scripts/measure_latency.py` | Member 2 + 4 | Computes collection-to-dashboard latency p95 from timestamps |
| `scripts/db_check_duplicates.sql` | Member 2 | Finds duplicate `payload_id` rows (expected: none) |
| `scripts/grep_secrets.sh` | Member 1 | Searches backend logs/DB dump for the seeded fake secrets (expected: no hits) |

### Reference: `scripts/check_env.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

if [ ! -f .env ]; then
  echo "ERROR: .env not found. Run: cp .env.example .env" >&2
  exit 1
fi

if grep -nE 'replace-with|change-me' .env; then
  echo "ERROR: placeholder values still present in .env (lines above)." >&2
  exit 1
fi

echo "OK: .env present and no placeholder values found."
```

### Reference: `scripts/outage_drill.sh`

```bash
#!/usr/bin/env bash
# Outage drill: backend down -> collector buffers -> backend up -> backlog delivered.
# Prints raw numbers; compare them yourself and record in FINAL_QUALITY_REPORT.md.
set -euo pipefail

OUTAGE_SECONDS="${1:-60}"

echo "[1] queue depth before:"
python -m collector.cli status

echo "[2] stopping backend for ${OUTAGE_SECONDS}s"
docker compose stop backend
sleep "${OUTAGE_SECONDS}"

echo "[3] queue depth during outage:"
python -m collector.cli status

echo "[4] starting backend"
docker compose start backend
sleep 30

echo "[5] queue depth after recovery:"
python -m collector.cli status

echo "[6] duplicate payload_id check (expected: no rows):"
docker compose exec -T postgres psql -U "${POSTGRES_USER:-obs_user}" -d "${POSTGRES_DB:-observability}" \
  -c "SELECT payload_id, COUNT(*) FROM telemetry_metadata GROUP BY payload_id HAVING COUNT(*) > 1;"
```

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `POSTGRES_PASSWORD` error on compose up | `.env` missing | `cp .env.example .env` and edit |
| Backend restarts repeatedly | DB not ready or wrong `DATABASE_URL` | `docker compose logs backend`; check password consistency |
| Port 5432/8000/5173 already in use | Another process | Stop it or change the host-side port in compose |
| Collector gets 401 | Wrong or missing `COLLECTOR_TOKEN` | Re-run seed, copy the new token |
| Collector cannot reach backend | Wrong `SAAS_BASE_URL` | Use `http://backend:8000` inside Docker, `http://localhost:8000` outside |
| Dashboard empty | Backend down or CORS | Check `CORS_ORIGINS`; try `VITE_USE_MOCK=true` |
| No anomalies on spike | Baseline not built yet | Wait for `AIOPS_MIN_BASELINE_SAMPLES` samples |
| Windows line-ending errors in `.sh` files | CRLF | `git config core.autocrlf input`, re-checkout |

## 10. Verification Log (fill in as commands are confirmed)

| Command / step | Verified by | Date/time | Result |
|---|---|---|---|
| `docker compose up -d --build` | | | |
| Backend `/health` | | | |
| `seed_demo.py` | | | |
| Collector run + data on dashboard | | | |
| `outage_drill.sh` | | | |
| Non-Docker backend run | | | |
| Non-Docker frontend run (mock mode) | | | |
| `pytest` in each module | | | |
