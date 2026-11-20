from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.db import get_db
from app.deps import get_current_user
from app.errors import Conflict, NotAuthenticated
from app.models import OWNER, Membership, User, Workshop
from app.security import (
    DUMMY_HASH,
    clear_session_cookies,
    create_session_token,
    hash_password,
    set_session_cookies,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def me_out(db: Session, user: User) -> schemas.MeOut:
    rows = db.execute(
        select(Membership, Workshop).join(Workshop, Workshop.id == Membership.workshop_id)
        .where(Membership.user_id == user.id).order_by(Workshop.id)
    ).all()
    return schemas.MeOut(
        id=user.id, email=user.email, full_name=user.full_name,
        memberships=[schemas.MembershipOut(workshop_id=w.id, workshop_name=w.name, role=m.role)
                     for m, w in rows],
    )


def _login_response(db: Session, user: User, response: Response) -> schemas.LoginOut:
    token, csrf = create_session_token(user.id)
    set_session_cookies(response, token, csrf)
    return schemas.LoginOut(user=me_out(db, user), csrf_token=csrf)


@router.post("/register", response_model=schemas.LoginOut, status_code=201,
             summary="Rejestracja: nowe konto i nowy warsztat (rola właściciela)")
def register(body: schemas.RegisterIn, response: Response, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email)):
        raise Conflict("Konto z tym adresem e-mail już istnieje.", code="EMAIL_TAKEN")
    user = User(email=body.email, full_name=body.full_name, password_hash=hash_password(body.password))
    workshop = Workshop(name=body.workshop_name)
    try:
        db.add_all([user, workshop])
        db.flush()
        db.add(Membership(user_id=user.id, workshop_id=workshop.id, role=OWNER))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Konto z tym adresem e-mail już istnieje.", code="EMAIL_TAKEN") from exc
    return _login_response(db, user, response)


@router.post("/login", response_model=schemas.LoginOut,
             summary="Logowanie – ustawia cookie sesji (HttpOnly) i zwraca token CSRF",
             responses={401: {"description": "Nieprawidłowy e-mail lub hasło"}})
def login(body: schemas.LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None:
        verify_password(DUMMY_HASH, body.password)
        raise NotAuthenticated("Nieprawidłowy e-mail lub hasło", code="BAD_CREDENTIALS")
    if not verify_password(user.password_hash, body.password):
        raise NotAuthenticated("Nieprawidłowy e-mail lub hasło", code="BAD_CREDENTIALS")
    return _login_response(db, user, response)


@router.post("/logout", status_code=204, summary="Wylogowanie (wymaga X-CSRF-Token)")
def logout(response: Response, _user: User = Depends(get_current_user)):
    clear_session_cookies(response)
    response.status_code = 204
    return response


@router.get("/me", response_model=schemas.MeOut, summary="Bieżący użytkownik i jego warsztaty")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return me_out(db, user)
