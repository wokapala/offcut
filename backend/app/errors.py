"""Błędy domenowe mapowane na odpowiedzi HTTP w jednolitym formacie:

    {"detail": "<komunikat po polsku>", "code": "<KOD>", "problems": [...]}
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, detail: str, code: str | None = None, problems: list[str] | None = None):
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        self.problems = problems or []


class NotAuthenticated(AppError):
    status_code = 401
    code = "NOT_AUTHENTICATED"


class Forbidden(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFound(AppError):
    status_code = 404
    code = "NOT_FOUND"


class Conflict(AppError):
    status_code = 409
    code = "CONFLICT"


class Unprocessable(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code, "problems": exc.problems},
        )

    @app.exception_handler(DataError)
    async def _data_error(_: Request, exc: DataError):
        # np. identyfikator większy niż zakres INTEGER w PostgreSQL – błąd danych, nie serwera
        return JSONResponse(
            status_code=422,
            content={"detail": "Nieprawidłowe dane wejściowe (wartość poza zakresem)",
                     "code": "VALIDATION_ERROR", "problems": []},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        problems = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
            problems.append(f"{loc}: {err.get('msg')}")
        return JSONResponse(
            status_code=422,
            content={"detail": "Nieprawidłowe dane wejściowe", "code": "VALIDATION_ERROR",
                     "problems": problems},
        )
