# ADR 0001: Keep durable workflow state in PostgreSQL

- Status: Accepted
- Date: 2026-07-24

## Context

Checkout can span several requests, fail between downstream calls, and resume after a
process restart. Order state, payment approval, idempotency ownership, audit history, and
events must not contradict one another.

## Decision

Use PostgreSQL as the durable consistency boundary. Persist explicit order states,
optimistic versions, transition records, hashed idempotency records, product snapshots,
and outbox events. A local command commits its state change, audit record, and event in
one transaction.

## Consequences

- Recovery does not depend on one API process remaining alive.
- PostgreSQL availability is required for durable mutations.
- State transitions remain queryable and reviewable.
- External calls cannot join the transaction and require explicit saga semantics.
- Splitting these records into separate databases would require a new consistency
  design, not only a schema migration.
