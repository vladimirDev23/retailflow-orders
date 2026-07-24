from fastapi import status
from fastapi.testclient import TestClient

from retailflow_orders.main import app


def test_liveness() -> None:
    response = TestClient(app).get("/api/v1/health/live")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "UP"}
