# Contributing

## Development workflow

1. Use Python 3.13 and uv 0.11.
2. Create a focused branch.
3. Add or update tests with the implementation.
4. Run the local quality gates from `README.md`.
5. Keep shared Alembic migrations append-only.
6. Use imperative, scoped commit messages.

## Code expectations

- Keep domain rules independent of FastAPI, SQLAlchemy, Redis, and Kafka.
- Do not hold a database transaction across a network call.
- Preserve idempotency for every mutation and downstream retry.
- Add an ADR when changing a cross-cutting architecture decision.
- Keep API contracts backward compatible within `/api/v1`.
- Never commit `.env`, credentials, tokens, generated caches, or real customer data.

## Pull request checklist

- [ ] behavior and tradeoffs are described;
- [ ] success, rejection, timeout, and retry paths are tested where relevant;
- [ ] Ruff, strict MyPy, coverage, migration, and package gates pass;
- [ ] container-backed integration tests pass for infrastructure changes;
- [ ] documentation and OpenAPI behavior remain accurate;
- [ ] no secret or generated artifact is included.
