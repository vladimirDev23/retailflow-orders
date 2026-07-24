# ADR 0002: Coordinate checkout as an orchestrated saga

- Status: Accepted
- Date: 2026-07-24

## Context

Inventory and payment are separate systems. A distributed transaction would couple
their availability and is not supported by their HTTP contracts. A workflow still needs
to handle decline, timeout, retry, and restart without overselling or charging twice.

## Decision

Model checkout as an explicit orchestrated saga. Reserve inventory before charging.
Persist a successful payment reference before asking Inventory to commit. Release an
active reservation when payment is explicitly declined. Use stable per-operation
idempotency keys for downstream reserve, charge, commit, and release calls.

Only safely recoverable states are processed automatically:

- `PAYMENT_PENDING` with a persisted payment reference retries Inventory commit;
- `COMPENSATION_PENDING` retries Inventory release.

An uncertain initial reservation remains client-retryable because the service does not
store raw payment methods.

## Consequences

- Every partial outcome has a durable, inspectable state.
- Compensation is a business action, not a database rollback.
- Clients may receive `503` while the durable workflow is still progressing.
- Downstream APIs must preserve their idempotency contracts.
- A production payment adapter must provide durable idempotent charge semantics.
