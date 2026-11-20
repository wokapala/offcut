"""Warsztat: członkowie, specyfikacje materiałów i magazyn odcinków."""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.api.serializers import spec_out, stock_out_many
from app.db import get_db
from app.deps import get_current_user, load_scoped, workshop_access
from app.errors import Conflict, NotFound
from app.models import (
    AVAILABLE,
    DISCARDED,
    DemandItem,
    MaterialSpec,
    Membership,
    StockItem,
    User,
)
from app.security import hash_password

router = APIRouter(prefix="/api", tags=["workshop"])


# --- Członkowie ------------------------------------------------------------------


@router.get("/workshops/{workshop_id}/members", response_model=list[schemas.MemberOut],
            summary="Członkowie warsztatu i ich role")
def list_members(workshop_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workshop_access(db, user, workshop_id)
    rows = db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id)
        .where(Membership.workshop_id == workshop_id).order_by(User.id)
    ).all()
    return [schemas.MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role) for m, u in rows]


@router.post("/workshops/{workshop_id}/members", response_model=schemas.MemberOut, status_code=201,
             summary="Dodanie członka warsztatu (tylko właściciel)")
def add_member(workshop_id: int, body: schemas.MemberIn, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    workshop_access(db, user, workshop_id).require_owner()
    # Tworzymy wyłącznie nowe konto – nie dopisujemy cudzych, istniejących kont bez ich zgody
    # i nie ujawniamy ich danych.
    if db.scalar(select(User.id).where(User.email == body.email)):
        raise Conflict("Konto z tym adresem e-mail już istnieje.", code="EMAIL_TAKEN")
    member = User(email=body.email, full_name=body.full_name, password_hash=hash_password(body.password))
    try:
        db.add(member)
        db.flush()
        db.add(Membership(user_id=member.id, workshop_id=workshop_id, role=body.role))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Konto z tym adresem e-mail już istnieje.", code="EMAIL_TAKEN") from exc
    return schemas.MemberOut(user_id=member.id, email=member.email, full_name=member.full_name, role=body.role)


# --- Specyfikacje materiałów ---------------------------------------------------------


@router.get("/workshops/{workshop_id}/materials", response_model=list[schemas.MaterialSpecOut],
            summary="Specyfikacje materiałów (materiał + przekrój)")
def list_materials(workshop_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workshop_access(db, user, workshop_id)
    specs = db.scalars(
        select(MaterialSpec).where(MaterialSpec.workshop_id == workshop_id)
        .order_by(MaterialSpec.material, MaterialSpec.section)
    )
    return [spec_out(s) for s in specs]


@router.post("/workshops/{workshop_id}/materials", response_model=schemas.MaterialSpecOut, status_code=201,
             summary="Nowa specyfikacja materiału (właściciel)")
def create_material(workshop_id: int, body: schemas.MaterialSpecIn, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    workshop_access(db, user, workshop_id).require_owner()
    spec = MaterialSpec(workshop_id=workshop_id, material=body.material, section=body.section)
    db.add(spec)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Taka specyfikacja (materiał + przekrój) już istnieje.", code="SPEC_EXISTS") from exc
    return spec_out(spec)


@router.delete("/materials/{spec_id}", status_code=204, summary="Usunięcie nieużywanej specyfikacji")
def delete_material(spec_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    spec, access = load_scoped(db, user, MaterialSpec, spec_id, lambda s: s.workshop_id, "specyfikacja")
    access.require_owner()
    used = db.scalar(select(StockItem.id).where(StockItem.material_spec_id == spec.id).limit(1)) or \
        db.scalar(select(DemandItem.id).where(DemandItem.material_spec_id == spec.id).limit(1))
    if used:
        raise Conflict("Specyfikacja jest używana przez odcinki lub zapotrzebowanie.", code="SPEC_IN_USE")
    db.delete(spec)
    db.commit()


# --- Magazyn -------------------------------------------------------------------------


def _spec_in_workshop(db: Session, spec_id: int, workshop_id: int) -> MaterialSpec:
    spec = db.get(MaterialSpec, spec_id)
    if spec is None or spec.workshop_id != workshop_id:
        raise NotFound("Nie znaleziono specyfikacji materiału w tym warsztacie")
    return spec


@router.get("/workshops/{workshop_id}/stock", response_model=list[schemas.StockOut],
            summary="Magazyn odcinków i resztek z filtrami")
def list_stock(
    workshop_id: int,
    status: schemas.StockStatus | Literal["ALL"] = Query("AVAILABLE"),
    material_spec_id: int | None = None,
    remnants_only: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workshop_access(db, user, workshop_id)
    stmt = select(StockItem).where(StockItem.workshop_id == workshop_id)
    if status != "ALL":
        stmt = stmt.where(StockItem.status == status)
    if material_spec_id is not None:
        stmt = stmt.where(StockItem.material_spec_id == material_spec_id)
    if remnants_only:
        stmt = stmt.where(StockItem.is_remnant.is_(True))
    items = list(db.scalars(stmt.order_by(StockItem.material_spec_id, StockItem.length_mm.desc(), StockItem.id)))
    return stock_out_many(db, items)


@router.post("/workshops/{workshop_id}/stock", response_model=list[schemas.StockOut], status_code=201,
             summary="Przyjęcie odcinków na magazyn (każda sztuka jako osobny odcinek)")
def create_stock(workshop_id: int, body: schemas.StockCreateIn, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    workshop_access(db, user, workshop_id).require_owner()
    _spec_in_workshop(db, body.material_spec_id, workshop_id)
    items = [
        StockItem(workshop_id=workshop_id, material_spec_id=body.material_spec_id, length_mm=body.length_mm,
                  status=AVAILABLE, is_remnant=body.is_remnant, label=body.label)
        for _ in range(body.quantity)
    ]
    db.add_all(items)
    db.commit()
    return stock_out_many(db, items)


@router.get("/stock/{stock_id}", response_model=schemas.StockOut, summary="Szczegóły odcinka z pochodzeniem")
def get_stock(stock_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item, _ = load_scoped(db, user, StockItem, stock_id, lambda s: s.workshop_id, "odcinek")
    return stock_out_many(db, [item])[0]


@router.delete("/stock/{stock_id}", response_model=schemas.StockOut,
               summary="Wycofanie odcinka z magazynu (status DISCARDED, historia zostaje)")
def discard_stock(stock_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item, access = load_scoped(db, user, StockItem, stock_id, lambda s: s.workshop_id, "odcinek",
                               for_update=True)
    access.require_owner()
    if item.status != AVAILABLE:
        raise Conflict(f"Można wycofać tylko dostępny odcinek (obecny status: {item.status}).",
                       code="STOCK_NOT_AVAILABLE")
    item.status = DISCARDED
    db.commit()
    return stock_out_many(db, [item])[0]
