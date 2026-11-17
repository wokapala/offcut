"""Uwierzytelnianie i autoryzacja egzekwowane po stronie backendu.

Zasada: każdy zasób jest odczytywany razem z jego warsztatem, a dostęp sprawdzany
przez członkostwo użytkownika. Zasób z cudzego warsztatu zwraca 404 (nie ujawniamy,
że istnieje) – również przy bezpośrednim odwołaniu po ID.
"""

from dataclasses import dataclass

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyCookie, APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import Forbidden, NotAuthenticated, NotFound
from app.models import OWNER, Membership, User
from app.security import CSRF_HEADER, SESSION_COOKIE, decode_session_token

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Schematy widoczne w Swagger UI (przycisk "Authorize").
session_cookie_scheme = APIKeyCookie(name=SESSION_COOKIE, auto_error=False,
                                     description="Cookie sesji ustawiane przez /api/auth/login")
csrf_header_scheme = APIKeyHeader(name=CSRF_HEADER, auto_error=False,
                                  description="Wartość csrf_token z odpowiedzi logowania")


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    session_token: str | None = Security(session_cookie_scheme),
    csrf_header: str | None = Security(csrf_header_scheme),
) -> User:
    if not session_token:
        raise NotAuthenticated("Zaloguj się, aby kontynuować")
    claims = decode_session_token(session_token)
    if claims is None:
        raise NotAuthenticated("Sesja wygasła lub jest nieprawidłowa – zaloguj się ponownie")
    if request.method not in SAFE_METHODS and csrf_header != claims.get("csrf"):
        raise Forbidden("Brak lub nieprawidłowy token CSRF", code="CSRF_FAILED")
    user = db.get(User, int(claims["sub"]))
    if user is None:
        raise NotAuthenticated("Konto nie istnieje")
    return user


@dataclass
class Access:
    user: User
    membership: Membership

    @property
    def workshop_id(self) -> int:
        return self.membership.workshop_id

    @property
    def is_owner(self) -> bool:
        return self.membership.role == OWNER

    def require_owner(self) -> None:
        if not self.is_owner:
            raise Forbidden("Ta operacja wymaga roli właściciela warsztatu", code="OWNER_REQUIRED")


def workshop_access(db: Session, user: User, workshop_id: int) -> Access:
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.workshop_id == workshop_id)
    )
    if membership is None:
        raise NotFound("Nie znaleziono warsztatu")
    return Access(user, membership)


def load_scoped(db: Session, user: User, model, obj_id: int, workshop_of, what: str,
                for_update: bool = False):
    """Ładuje obiekt i sprawdza członkostwo w jego warsztacie (inaczej 404)."""
    stmt = select(model).where(model.id == obj_id)
    if for_update:
        stmt = stmt.with_for_update()
    obj = db.scalar(stmt)
    if obj is None:
        raise NotFound(f"Nie znaleziono: {what}")
    try:
        access = workshop_access(db, user, workshop_of(obj))
    except NotFound:
        raise NotFound(f"Nie znaleziono: {what}") from None
    return obj, access
