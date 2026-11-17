from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for domain errors. code is a stable machine-readable string."""

    status_code = 400

    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AppError):
    status_code = 404

    def __init__(self, message: str = "Resource not found", details: dict | None = None):
        super().__init__("NOT_FOUND", message, details)


class ConflictError(AppError):
    status_code = 409

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(code, message, details)


class SlotTakenError(ConflictError):
    def __init__(self, slot_id: str):
        super().__init__("SLOT_TAKEN", "This slot was just taken by another request.", {"slot_id": slot_id})


class SlotUnavailableError(ConflictError):
    """The option stopped being feasible (rule, ETA, dock event, hours...). Distinct from SLOT_TAKEN."""

    def __init__(self, reasons: list[str]):
        super().__init__("SLOT_UNAVAILABLE", "This option is no longer feasible.", {"reasons": reasons})


class ForbiddenError(AppError):
    status_code = 403

    def __init__(self, message: str = "Not permitted", details: dict | None = None):
        super().__init__("FORBIDDEN", message, details)


class ValidationAppError(AppError):
    status_code = 422

    def __init__(self, message: str, details: dict | None = None):
        super().__init__("VALIDATION_ERROR", message, details)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )
