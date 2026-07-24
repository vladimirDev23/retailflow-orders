# ADR 0004: Use Redis only for stale-tolerant projections and Celery

- Status: Accepted
- Date: 2026-07-24

## Context

Product snapshots are read frequently and can tolerate bounded staleness. Order state,
payment references, and idempotency cannot. Redis is also a convenient local broker and
result backend for Celery.

Celery 5.6 and Kombu currently constrain the compatible redis-py line below 6.5, while
the Redis server can run a newer 8.x release.

## Decision

Cache only product snapshots with a short TTL and PostgreSQL fallback. Keep all order,
idempotency, audit, and outbox authority in PostgreSQL. Pin the Python Redis client to a
Celery-compatible 6.4 release and run Redis Server 8 in the Compose environment; treat
client and server versions as separate compatibility decisions.

## Consequences

- Redis outages degrade catalog reads instead of corrupting checkout state.
- A stale snapshot can temporarily expose an outdated price or availability flag.
- Cache invalidation is TTL-based until a catalog event consumer is introduced.
- The redis-py pin must be revisited when Celery/Kombu broadens compatibility.
- Redis persistence settings in Compose are deliberately disposable and not a production
  topology.
