# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-07-24

### Added

- async FastAPI order API with Argon2/JWT authentication;
- explicit checkout state machine and transition audit;
- PostgreSQL persistence, optimistic versions, Alembic migration, and product snapshots;
- persistent request idempotency with canonical request fingerprints and leases;
- Inventory reservation integration with bounded idempotent retries;
- payment-safe checkout recovery and declined-payment compensation;
- Redis product cache and Celery reconciliation;
- transactional Kafka outbox with leased `SKIP LOCKED` dispatch;
- unit, contract, Testcontainers, migration, and Compose smoke tests;
- CI, dependency audit, secret-history scan, and Dependabot configuration.

[Unreleased]: https://github.com/vladimirDev23/retailflow-orders/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vladimirDev23/retailflow-orders/releases/tag/v0.1.0
