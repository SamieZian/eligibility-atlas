# eligibility-atlas

**Bitemporal enrollment** — the core of the Eligibility & Enrollment Platform.

## What this service does

Atlas owns member eligibility over time. It maintains a **bitemporal** `enrollments` table — every row has both a *valid time* (when coverage is true in the real world) and a *transaction time* (when the system learned that fact). Retro-active 834 corrections never overwrite history; they close the existing row's `txn_to` and open a new corrected row.

Atlas exposes a command API (`ADD`, `CHANGE`, `TERMINATE`, `REINSTATE`, `CORRECTION`) and a timeline query. Each write also lands in the `outbox` table so the relay worker can publish events to Pub/Sub atomically with the domain mutation.

Idempotency for 834 retries is keyed off `(trading_partner, ISA13, GS06, ST02, INS_position)` — repeated deliveries are silently dropped via the `processed_segments` table.

Saga orchestration lives here too — multi-step workflows like `REPLACE_FILE` (full-file enrollment refresh) are managed via a hand-rolled finite-state machine with compensating actions on failure.

This is **one of 7 microservices** in the [Eligibility & Enrollment Platform](https://github.com/SamieZian/eligibility-platform). Each service has its own repo, its own database, its own Dockerfile, its own deployment lifecycle.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Docker | 24+ | Container runtime |
| Docker Compose | v2 (the `docker compose` plugin) | Local orchestration |
| Python | 3.11+ | Standalone dev (optional) |
| GNU Make | any recent | Convenience targets (optional) |

The easiest way to use this service is via the orchestration repo:
```bash
git clone https://github.com/SamieZian/eligibility-platform
cd eligibility-platform
./bootstrap.sh         # clones this repo and 6 siblings
make up                # boots the whole stack with this svc included
```

## Companion repos

| Repo | What |
|---|---|
| [`eligibility-platform`](https://github.com/SamieZian/eligibility-platform) | Orchestration + docker-compose + sample 834 + demo |
| [`eligibility-atlas`](https://github.com/SamieZian/eligibility-atlas) | Bitemporal enrollment service |
| [`eligibility-member`](https://github.com/SamieZian/eligibility-member) | Members + dependents (KMS-encrypted SSN) |
| [`eligibility-group`](https://github.com/SamieZian/eligibility-group) | Payer / employer / subgroup / plan visibility |
| [`eligibility-plan`](https://github.com/SamieZian/eligibility-plan) | Plan catalog (Redis cache-aside) |
| [`eligibility-bff`](https://github.com/SamieZian/eligibility-bff) | GraphQL gateway + file upload |
| [`eligibility-workers`](https://github.com/SamieZian/eligibility-workers) | Stateless workers — ingestion / projector / outbox-relay |
| [`eligibility-frontend`](https://github.com/SamieZian/eligibility-frontend) | React + TS UI |

## Quickstart (standalone, with this repo only)

```bash
# 1. Configure
cp .env.example .env
# (edit values if needed — defaults work for local docker)

# 2. Build the image
docker build -t eligibility-atlas:local .

# 3. Spin a Postgres for it
docker run -d --name pg-atlas \
  -e POSTGRES_PASSWORD=dev_pw \
  -p 5441:5432 postgres:15-alpine

# 4. Run the service against that DB
docker run --rm -p 6441:8000 \
  --env-file .env \
  -e DATABASE_URL=postgresql+psycopg://postgres:dev_pw@host.docker.internal:5441/postgres \
  eligibility-atlas:local

# 5. Health check
curl http://localhost:6441/livez
```

## Develop locally without Docker

```bash
# Prereqs: Python 3.11+, Poetry 1.8+
poetry install            # creates .venv and installs everything
poetry run python -m app.main
poetry run pytest tests -q
```

## Project layout (hexagonal)

```
.
├── app/
│   ├── domain/         # Pure business logic — no I/O
│   ├── application/    # Use-cases, command handlers
│   ├── infra/          # SQLAlchemy repos, KMS, Redis, ORM models
│   ├── interfaces/     # FastAPI routers (HTTP)
│   ├── settings.py     # Pydantic env-driven config
│   └── main.py         # FastAPI app + lifespan
├── tests/              # pytest unit tests
├── migrations/         # Alembic (prod schema migrations)
├── libs/               # Vendored shared code
│   └── python-common/  # outbox, pubsub, errors, retry, circuit breaker, kms
├── .env.example        # All env vars documented
├── Dockerfile
├── pyproject.toml
└── README.md
```

## Environment variables

See [`.env.example`](.env.example) for the full list with defaults. Required:

- `SERVICE_NAME` — used in logs/traces
- `DATABASE_URL` — Postgres connection string
- `PUBSUB_PROJECT_ID` — Pub/Sub project (any value for local emulator)
- `PUBSUB_EMULATOR_HOST` — `pubsub:8085` when running with compose, unset in prod

Optional:
- `LOG_LEVEL` (`INFO`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` — when set, traces export to that endpoint
- `TENANT_DEFAULT` — fallback tenant id when no header

## API

See `app/interfaces/api.py` for the route list. Standard endpoints:

- `GET /livez` → liveness probe
- `GET /readyz` → readiness probe (checks deps reachable)

## Testing via curl

With this service running standalone on port **8001** (e.g. via `docker compose up atlas atlas_db pubsub`), you can drive it end-to-end without the BFF.

```bash
BASE=http://localhost:8001
T=11111111-1111-1111-1111-111111111111
IDEM=$(uuidgen)
```

**Liveness + readiness**

```bash
curl -sf $BASE/livez    # {"status":"ok"}
curl -sf $BASE/readyz   # {"db":"ok"} or 503 on drain
```

**ADD an enrollment** (idempotent — reuse `Idempotency-Key` to replay)

```bash
MEMBER=$(uuidgen); PLAN=$(uuidgen); EMP=$(uuidgen)
curl -s -X POST $BASE/commands \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Id: $T" \
  -H "Idempotency-Key: $IDEM" \
  -d "{
    \"command_type\": \"ADD\",
    \"tenant_id\": \"$T\",
    \"employer_id\": \"$EMP\",
    \"plan_id\": \"$PLAN\",
    \"member_id\": \"$MEMBER\",
    \"relationship\": \"subscriber\",
    \"valid_from\": \"2026-05-01\"
  }" | jq .
# → {"enrollment_ids": ["..."]}
```

**TERMINATE** (closes the in-force row; bitemporally preserved for audit)

```bash
curl -s -X POST $BASE/commands \
  -H "Content-Type: application/json" -H "X-Tenant-Id: $T" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d "{
    \"command_type\": \"TERMINATE\",
    \"tenant_id\": \"$T\", \"member_id\": \"$MEMBER\", \"plan_id\": \"$PLAN\",
    \"valid_to\": \"2026-07-31\"
  }" | jq .
```

**Timeline** — full bitemporal history (current + superseded segments)

```bash
curl -s "$BASE/members/$MEMBER/timeline" -H "X-Tenant-Id: $T" | jq .
# → {"segments": [{..., "is_in_force": true, "txn_from": "...", "txn_to": "..."}]}
```

**Replay an Idempotency-Key** — same key + same body → cached response with `Idempotent-Replay: true` header.

**Error envelope** (e.g. overlapping enrollment):

```json
{
  "error": {
    "code": "ENROLLMENT_OVERLAP",
    "message": "Member already has active coverage for this plan overlapping the requested period.",
    "correlation_id": "...",
    "retryable": false,
    "details": {}
  }
}
```

## Patterns used

- Hexagonal architecture (domain / application / infra / interfaces)
- Transactional outbox for at-least-once event delivery
- Idempotent commands (each command's effect is repeatable)
- Structured JSON logs with correlation ID propagation
- OpenTelemetry traces (BFF → service → DB)
- Circuit breakers on outbound HTTP

## License

MIT.
