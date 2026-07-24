import os
import shutil
import subprocess
import sys
from collections.abc import Iterator

import pytest
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer


def require_docker() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for integration tests")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    require_docker()
    with PostgresContainer(
        image="postgres:17.10-bookworm",
        driver="asyncpg",
    ) as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def migrated_postgres_url(postgres_url: str) -> str:
    run_alembic(postgres_url, "upgrade", "head")
    return postgres_url


@pytest.fixture(scope="session")
def kafka_bootstrap_servers() -> Iterator[str]:
    require_docker()
    with KafkaContainer("confluentinc/cp-kafka:7.6.0").with_kraft() as kafka:
        yield kafka.get_bootstrap_server()


def run_alembic(database_url: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(  # noqa: S603 - executable and arguments are test-owned
        [sys.executable, "-m", "alembic", *arguments],
        check=True,
        env=environment,
    )
