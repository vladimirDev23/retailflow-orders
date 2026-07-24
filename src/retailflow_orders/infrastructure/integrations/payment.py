from hashlib import sha256
from uuid import UUID

from retailflow_orders.application.ports import PaymentDecision

APPROVED_PAYMENT_METHOD = "pm_demo_approved"
DECLINED_PAYMENT_METHOD = "pm_demo_declined"
REFERENCE_LENGTH = 24


class DeterministicPaymentGateway:
    """A local provider simulator with stable idempotent outcomes."""

    async def charge(
        self,
        *,
        order_id: UUID,
        amount: object,
        currency: str,
        payment_token: str,
        idempotency_key: str,
    ) -> PaymentDecision:
        if payment_token == APPROVED_PAYMENT_METHOD:
            digest = sha256(f"{order_id}:{idempotency_key}".encode()).hexdigest()
            return PaymentDecision(
                approved=True,
                reference=f"pay_{digest[:REFERENCE_LENGTH]}",
                reason=None,
            )
        reason = (
            "Payment was declined by the deterministic provider"
            if payment_token == DECLINED_PAYMENT_METHOD
            else "Unknown local payment token"
        )
        return PaymentDecision(approved=False, reference=None, reason=reason)
