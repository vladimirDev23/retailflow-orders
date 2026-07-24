class ApplicationError(Exception):
    """Base class for use-case failures."""


class OrderNotFoundError(ApplicationError):
    """Raised when an order is absent or not visible to the actor."""


class ProductUnavailableError(ApplicationError):
    """Raised when a requested product snapshot cannot be ordered."""


class CheckoutPendingError(ApplicationError):
    """Raised when an external outcome is uncertain and reconciliation is required."""


class InventoryRejectedError(ApplicationError):
    """Raised when Inventory explicitly rejects a reservation."""


class InventoryUnavailableError(ApplicationError):
    """Raised when Inventory cannot provide a conclusive response."""
