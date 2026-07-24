from fastapi import status
from fastapi.testclient import TestClient

from retailflow_orders.api.models import TokenRequest
from retailflow_orders.config import Settings
from retailflow_orders.main import create_app
from retailflow_orders.observability import configure_logging


def test_default_admin_email_is_accepted_by_login_contract() -> None:
    settings = Settings()
    request = TokenRequest(
        email=settings.admin_email,
        password=settings.admin_password.get_secret_value(),
    )

    assert request.email == settings.admin_email


def test_openapi_exposes_product_workflows_and_bearer_authentication() -> None:
    schema = create_app().openapi()

    assert "/api/v1/auth/token" in schema["paths"]
    assert "/api/v1/orders" in schema["paths"]
    assert "/api/v1/orders/{order_id}/checkout" in schema["paths"]
    assert schema["components"]["securitySchemes"]["OAuth2PasswordBearer"]["type"] == "oauth2"


def test_middleware_returns_existing_correlation_id() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/api/v1/health/live",
        headers={"X-Correlation-ID": "corr-api-test-100"},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["X-Correlation-ID"] == "corr-api-test-100"


def test_structured_logging_configuration_accepts_runtime_level() -> None:
    configure_logging("INFO")
