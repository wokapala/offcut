"""Hasła (argon2id), sesja w podpisanym tokenie w cookie HttpOnly oraz token CSRF.

Przepływ:
  * logowanie ustawia cookie ``offcut_session`` (HttpOnly, SameSite=Lax) z tokenem JWT
    zawierającym id użytkownika i losowy token CSRF,
  * ten sam token CSRF trafia do cookie ``offcut_csrf`` (czytelnego dla JS) i do odpowiedzi,
  * każde żądanie zmieniające stan musi mieć nagłówek ``X-CSRF-Token`` równy wartości
    z podpisanego tokenu sesji (double submit). Obca strona nie zna tej wartości.
"""

import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Response

from app.config import get_settings

SESSION_COOKIE = "offcut_session"
CSRF_COOKIE = "offcut_csrf"
CSRF_HEADER = "X-CSRF-Token"
_ALGORITHM = "HS256"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


# Stały hash do porównania przy nieistniejącym użytkowniku – podobny czas odpowiedzi.
DUMMY_HASH = _hasher.hash("offcut-dummy-password")


def create_session_token(user_id: int) -> tuple[str, str]:
    settings = get_settings()
    csrf = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user_id), "csrf": csrf, "iat": now,
         "exp": now + timedelta(hours=settings.session_hours)},
        settings.secret_key,
        algorithm=_ALGORITHM,
    )
    return token, csrf


def decode_session_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None


def set_session_cookies(response: Response, token: str, csrf: str) -> None:
    settings = get_settings()
    max_age = settings.session_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True,
                        secure=settings.cookie_secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=max_age, httponly=False,
                        secure=settings.cookie_secure, samesite="lax", path="/")


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
