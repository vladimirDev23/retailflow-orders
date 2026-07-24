# Architecture Decision Records

Accepted decisions remain as historical records. A later ADR may supersede one without
rewriting its original context.

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-postgresql-workflow-state.md) | Keep durable workflow state in PostgreSQL | Accepted |
| [0002](0002-orchestrated-checkout-saga.md) | Coordinate checkout as an orchestrated saga | Accepted |
| [0003](0003-transactional-outbox.md) | Publish order events through a transactional outbox | Accepted |
| [0004](0004-redis-cache-boundary.md) | Use Redis only for stale-tolerant projections and Celery | Accepted |
