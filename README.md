# RetailFlow Orders

RetailFlow Orders is an order orchestration and checkout service for a retail/e-commerce
platform. It coordinates inventory reservations and deterministic payment outcomes while
keeping retries safe, state transitions auditable, and domain events recoverable.

The service is under active local development and is not published yet.

## Planned engineering scope

- FastAPI and fully asynchronous SQLAlchemy/PostgreSQL persistence;
- explicit order state machine and saga-like compensation;
- persistent idempotency for mutation endpoints;
- Redis-backed cache and Celery task execution;
- Inventory Service HTTP integration with bounded retries;
- transactional outbox to Kafka and inbox deduplication;
- unit, integration, contract, security, and container smoke gates.
