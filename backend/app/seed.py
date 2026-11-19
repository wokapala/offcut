"""Dane demonstracyjne. Uruchomienie: ``python -m app.seed``.

Idempotentne: ponowne uruchomienie nie duplikuje danych (szuka po e-mailu / nazwie).
Konta są WYŁĄCZNIE lokalnymi kontami demo – hasła są jawne celowo.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    OPERATOR,
    OWNER,
    DemandItem,
    MaterialSpec,
    Membership,
    Project,
    StockItem,
    User,
    Workshop,
)
from app.security import hash_password

DEMO_PASSWORD = "Demo1234!"

DEMO_USERS = [
    ("wlasciciel@offcut.demo", "Anna Właścicielka"),
    ("operator@offcut.demo", "Piotr Operator"),
    ("obcy@offcut.demo", "Tomasz Z Innego Warsztatu"),
]


def _user(db: Session, email: str, name: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, full_name=name, password_hash=hash_password(DEMO_PASSWORD))
        db.add(user)
        db.flush()
    return user


def _workshop(db: Session, name: str, members: list[tuple[User, str]]) -> tuple[Workshop, bool]:
    ws = db.scalar(select(Workshop).where(Workshop.name == name))
    created = ws is None
    if created:
        ws = Workshop(name=name)
        db.add(ws)
        db.flush()
    for user, role in members:
        exists = db.scalar(select(Membership).where(Membership.user_id == user.id,
                                                    Membership.workshop_id == ws.id))
        if exists is None:
            db.add(Membership(user_id=user.id, workshop_id=ws.id, role=role))
    return ws, created


def _spec(db: Session, ws: Workshop, material: str, section: str) -> MaterialSpec:
    spec = db.scalar(select(MaterialSpec).where(MaterialSpec.workshop_id == ws.id,
                                                MaterialSpec.material == material,
                                                MaterialSpec.section == section))
    if spec is None:
        spec = MaterialSpec(workshop_id=ws.id, material=material, section=section)
        db.add(spec)
        db.flush()
    return spec


def _stock(db: Session, ws: Workshop, spec: MaterialSpec, batches: list[tuple[list[int], bool, str]]):
    """Odcinki tworzymy tylko dla specyfikacji, która nie ma jeszcze żadnego odcinka (idempotencja)."""
    if db.scalar(select(StockItem.id).where(StockItem.material_spec_id == spec.id).limit(1)):
        return
    for lengths, remnant, label in batches:
        for length in lengths:
            db.add(StockItem(workshop_id=ws.id, material_spec_id=spec.id, length_mm=length,
                             status="AVAILABLE", is_remnant=remnant, label=label))


def _project(db: Session, ws: Workshop, owner: User, name: str, kerf: int, min_remnant: int,
             demand: list[tuple[MaterialSpec, int, int, str]]) -> None:
    if db.scalar(select(Project).where(Project.workshop_id == ws.id, Project.name == name)):
        return
    project = Project(workshop_id=ws.id, name=name, kerf_mm=kerf, min_remnant_mm=min_remnant,
                      revision=1, created_by_id=owner.id)
    db.add(project)
    db.flush()
    for spec, length, qty, label in demand:
        db.add(DemandItem(project_id=project.id, material_spec_id=spec.id, length_mm=length,
                          quantity=qty, label=label))


def seed(db: Session) -> None:
    owner, operator, other = (_user(db, e, n) for e, n in DEMO_USERS)
    ws, _ = _workshop(db, "Warsztat Demo", [(owner, OWNER), (operator, OPERATOR)])
    pine = _spec(db, ws, "Sosna", "40x20 mm")
    alu = _spec(db, ws, "Aluminium", "profil 20x20x1,5 mm")
    spruce = _spec(db, ws, "Świerk", "45x45 mm")
    # Przykład z docs/ALGORITHM.md – heurystyka zużywa 5450 mm, branch and bound 4900 mm.
    _stock(db, ws, pine, [([1250, 1900, 1400, 900], True, "Resztka z wcześniejszych prac"),
                          ([3000, 3000, 3000], False, "Nowa listwa 3 m")])
    _stock(db, ws, alu, [([6000, 6000], False, "Nowy profil 6 m"), ([2200], True, "Resztka profilu")])
    # Większy przykład (13 elementów) – heurystyka 14 150 mm / 8 odcinków, B&B 10 200 mm / 4 odcinki.
    _stock(db, ws, spruce, [([2100, 1300, 1100, 850, 700], True, "Resztka kantówki"),
                            ([2700] * 5, False, "Nowa kantówka 2,7 m")])
    _project(db, ws, owner, "Regał na narzędzia", 3, 300, [
        (pine, 950, 2, "Słupek"),
        (pine, 600, 1, "Poprzeczka górna"),
        (pine, 560, 3, "Półka – listwa nośna"),
    ])
    # Przypadek remisu: obie metody wybierają tę samą resztkę 2200 mm.
    _project(db, ws, owner, "Wsporniki z profilu", 2, 300, [
        (alu, 1000, 2, "Ramię wspornika"),
        (alu, 150, 1, "Łącznik"),
    ])
    _project(db, ws, owner, "Stojak na drewno kominkowe", 3, 300, [
        (spruce, 1150, 4, "Słupek"),
        (spruce, 760, 4, "Rygiel"),
        (spruce, 520, 3, "Poprzeczka"),
        (spruce, 420, 2, "Zastrzał"),
    ])
    _project(db, ws, owner, "Listwy przypodłogowe (za mało materiału)", 3, 300, [
        (pine, 2900, 5, "Listwa ścienna"),
    ])

    other_ws, _ = _workshop(db, "Stolarnia Obca", [(other, OWNER)])
    other_spec = _spec(db, other_ws, "Dąb", "60x20 mm")
    _stock(db, other_ws, other_spec, [([2500, 2500], False, "Deska dębowa")])
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        seed(db)
    print("Dane demo gotowe. Konta (hasło dla wszystkich: %s):" % DEMO_PASSWORD)
    for email, name in DEMO_USERS:
        print(f"  {email:28} {name}")


if __name__ == "__main__":
    main()
