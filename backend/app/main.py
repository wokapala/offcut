import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, inventory, projects
from app.config import get_settings
from app.db import engine
from app.errors import register_error_handlers

DESCRIPTION = """
REST API aplikacji **Offcut** – planowanie cięcia listew i profili z wykorzystaniem resztek.

**Uwierzytelnianie:** `POST /api/auth/login` ustawia cookie sesji (HttpOnly) i zwraca `csrf_token`.
Każde żądanie zmieniające stan (POST/PATCH/DELETE) wymaga nagłówka `X-CSRF-Token`.
W Swagger UI: zaloguj się, skopiuj `csrf_token` i wklej go w *Authorize → X-CSRF-Token*.

**Format błędów:** `{"detail": "...", "code": "...", "problems": [...]}`
– 401 brak sesji, 403 brak uprawnień / CSRF, 404 brak zasobu lub cudzy warsztat,
409 konflikt stanu (rezerwacja, nieaktualny plan), 422 błędne dane.

Wszystkie długości są liczbami całkowitymi w milimetrach.
"""


PLACEHOLDER_SECRET = "zmien-mnie-na-dlugi-losowy-ciag"  # wartość z .env.example


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.secret_key == PLACEHOLDER_SECRET or len(settings.secret_key) < 32:
        logging.getLogger("offcut").warning(
            "OFFCUT_SECRET_KEY to wartość przykładowa lub jest krótszy niż 32 znaki – "
            "wystarczy lokalnie, ale poza własnym komputerem ustaw własny losowy klucz."
        )
    app = FastAPI(title="Offcut API", version="1.0.0", description=DESCRIPTION,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(inventory.router)
    app.include_router(projects.router)

    @app.get("/api/health", tags=["system"], summary="Stan usługi i połączenia z bazą")
    def health():
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}

    return app


app = create_app()
