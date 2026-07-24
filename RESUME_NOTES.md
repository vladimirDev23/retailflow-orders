# Resume Notes

This file separates implemented evidence from topics that must be practiced before being
presented in an interview.

## Verified claims

- Designed and implemented a Python 3.13 / FastAPI order orchestration service with
  versioned REST contracts and server-owned product price snapshots.
- Modelled an explicit checkout state machine with reservation failure, confirmed order,
  and declined-payment compensation paths.
- Kept external HTTP calls outside PostgreSQL transactions and used stable downstream
  idempotency keys with bounded retries.
- Prevented repeat charging after an uncertain Inventory commit by persisting the payment
  reference before commit reconciliation.
- Implemented durable request idempotency with canonical SHA-256 request fingerprints,
  execution leases, resource binding, and deterministic replay.
- Implemented SQLAlchemy 2 async persistence, optimistic order versions, immutable
  transition audit, and Alembic upgrade/downgrade definitions.
- Added a PostgreSQL transactional outbox, leased `SKIP LOCKED` claims, idempotent Kafka
  producer settings, retry metadata, and Celery dispatch.
- Added Redis product projection caching with malformed-entry and outage fallback to
  PostgreSQL.
- Added Argon2 password hashing, issuer/audience/expiry-validated JWTs, ownership checks,
  problem responses, correlation IDs, Prometheus metrics, and structured logs.
- Added PostgreSQL, Redis, and Kafka Testcontainers scenarios plus a complete Docker
  Compose smoke workflow.
- Locally verified strict MyPy and Ruff with zero findings, 71 passing fast tests, 87.3%
  branch-aware aggregate coverage, Alembic offline SQL, package build, and a pip-audit
  result with no known runtime dependency vulnerabilities.
- Added GitHub Actions definitions for unit, integration, package, container, Gitleaks,
  dependency-audit, and Dependabot gates.

## Learning required

- Run and inspect the complete GitHub Actions integration and Compose jobs before
  claiming the container topology is verified.
- Practice explaining why client idempotency, payment-provider idempotency, and Inventory
  idempotency solve different duplicate-execution risks.
- Be able to explain why an idempotent Kafka producer does not make the full outbox
  pipeline exactly-once.
- Exercise Kafka outage/recovery and inspect outbox lease, attempts, and lag.
- Practice reconciling `PAYMENT_PENDING` and `COMPENSATION_PENDING` using the runbook.
- Understand when an orchestrated saga should be replaced by choreography or a workflow
  engine.
- Be ready to compare local HS256 authentication with OIDC, JWKS rotation, asymmetric
  signing, and service identity.
