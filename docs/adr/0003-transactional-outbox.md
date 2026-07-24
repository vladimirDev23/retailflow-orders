# ADR 0003: Publish order events through a transactional outbox

- Status: Accepted
- Date: 2026-07-24

## Context

Directly publishing to Kafka next to a PostgreSQL commit creates a dual-write race. The
database can commit while Kafka is unavailable, or Kafka can accept an event for a
transaction that later rolls back.

## Decision

Append each domain event to `outbox_events` in the same transaction as the order change.
Celery workers claim unpublished rows with `FOR UPDATE SKIP LOCKED`, publish through an
idempotent Kafka producer, and record acknowledgement in a later transaction. Failed
attempts release the lease and retain a redacted error.

## Consequences

- Every committed order change has a durable event awaiting delivery.
- API latency is independent of Kafka acknowledgement time.
- Delivery is at-least-once; consumers must deduplicate by `eventId`.
- Publication lag and failed attempts need monitoring.
- A crash between Kafka acknowledgement and the published marker can create a duplicate.
