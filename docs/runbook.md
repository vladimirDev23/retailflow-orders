# RetailFlow Orders Runbook

This runbook covers the self-contained Docker Compose environment. A production
deployment additionally needs managed secrets, backups, alerting, an external identity
provider, and a real payment adapter.

## Service checks

```bash
curl --fail http://localhost:8000/api/v1/health/live
curl --fail http://localhost:8000/api/v1/health/ready
curl --fail http://localhost:8000/metrics
docker compose ps
docker compose logs --tail=200 api worker beat
```

Readiness requires PostgreSQL and Redis. Kafka failure does not invalidate already
committed orders because unpublished events remain in PostgreSQL.

## Common failure modes

### API never becomes ready

1. Inspect `docker compose ps` and API logs.
2. Confirm every placeholder in `.env` was replaced.
3. Check PostgreSQL and Redis health.
4. Look for an Alembic failure. Never edit an applied migration; add a new revision.
5. Confirm `JWT_SECRET` contains at least 32 characters.

### Checkout returns `503`

The downstream outcome is uncertain. Preserve the same client `Idempotency-Key` and
payload when retrying. Inspect the order status:

- `PENDING_RESERVATION`: retry from the client; no payment was requested.
- `PAYMENT_PENDING` with `payment_reference`: the reconciler can retry commit without
  charging again.
- `COMPENSATION_PENDING`: the reconciler can retry reservation release.

Do not manually force a terminal status before comparing the Inventory reservation and
payment-provider records.

### Checkout returns an idempotency conflict

One key was reused with a different payload or resource. Generate one stable key per
logical command and preserve it only for exact retries. Do not delete the record to make
a conflicting request succeed.

### Kafka is unavailable

Orders continue to commit with durable outbox events. Restore Kafka and inspect backlog:

```sql
select count(*) as pending,
       min(occurred_at) as oldest,
       max(attempts) as max_attempts
from outbox_events
where published_at is null;
```

Failed rows retain `last_error`. Do not mark them published unless downstream delivery
has been independently reconciled.

### Worker is not progressing

1. Confirm one `beat` service and at least one `worker` are running.
2. Check Redis broker connectivity.
3. Inspect Celery task errors.
4. Confirm Kafka DNS and listener settings from the worker container.
5. Check stale outbox leases; the default lease expires automatically.

### Redis is unavailable

Readiness reports `DOWN`, but product lookup code can fall back to PostgreSQL. Restore
Redis before normal operation so request health and Celery scheduling are reliable.
Never reconstruct orders from Redis.

## Recovery and data handling

- PostgreSQL is the source of truth; back it up before destructive maintenance.
- `docker compose down` preserves the named PostgreSQL volume.
- `docker compose down --volumes` deletes local database state and is only for an
  intentional disposable reset.
- Kafka consumers must tolerate duplicate events.
- Rotate any exposed credential before considering Git history cleanup.

## Production signals

- HTTP error rate and latency by route;
- oldest unpublished outbox age and retry count;
- count and age of recoverable checkout states;
- idempotency conflicts and in-progress lease conflicts;
- PostgreSQL pool saturation and transaction failures;
- Redis and Celery queue health;
- payment declines versus provider transport failures;
- backup age and restore-test result.
