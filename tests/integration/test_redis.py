from collections.abc import Iterator

import pytest
from redis.asyncio import Redis
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from tests.integration.conftest import require_docker

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis_url() -> Iterator[str]:
    require_docker()
    with DockerContainer("redis:8.2.7-bookworm").with_exposed_ports(6379) as redis:
        wait_for_logs(redis, "Ready to accept connections")
        host = redis.get_container_host_ip()
        port = redis.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


async def test_redis_round_trip(redis_url: str) -> None:
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        await client.set("retailflow:integration", "ready", ex=30)
        assert await client.get("retailflow:integration") == "ready"
    finally:
        await client.aclose()
