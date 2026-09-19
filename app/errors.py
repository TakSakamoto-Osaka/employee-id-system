import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from .services.numbering import SequenceExhaustedError
from .services.validation import FieldError


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id", str(uuid.uuid4()))


async def field_error_handler(request: Request, exc: FieldError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "message": "One or more fields are invalid.",
            "field_errors": exc.errors,
            "request_id": _request_id(request),
        },
    )


async def sequence_exhausted_handler(request: Request, exc: SequenceExhaustedError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "code": "SEQUENCE_EXHAUSTED",
            "message": str(exc),
            "field_errors": [],
            "request_id": _request_id(request),
        },
    )


def register_exception_handlers(app) -> None:
    app.add_exception_handler(FieldError, field_error_handler)
    app.add_exception_handler(SequenceExhaustedError, sequence_exhausted_handler)
