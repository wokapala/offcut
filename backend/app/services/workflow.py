"""Cykl życia planu: DRAFT -> RESERVED -> EXECUTED, oraz RESERVED -> DRAFT (zwolnienie).

Ochrona przed podwójnym zużyciem materiału (warstwy):
  1. jedna transakcja na operację,
  2. blokady wierszy ``SELECT ... FOR UPDATE`` w stałej kolejności:
     plan -> projekt -> odcinki (rosnąco po id, co zapobiega zakleszczeniom),
  3. warunkowy UPDATE odcinków (``WHERE status = 'AVAILABLE'``) z kontrolą liczby wierszy,
  4. ograniczenia w bazie: CHECK spójności rezerwacji, częściowy UNIQUE na jeden aktywny
     plan projektu, UNIQUE(plan_id) w plan_executions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import load_scoped
from app.errors import Conflict
from app.models import (
    AVAILABLE,
    CONSUMED,
    PLAN_DRAFT,
    PLAN_EXECUTED,
    PLAN_RESERVED,
    RESERVED,
    CuttingPlan,
    PlanExecution,
    Project,
    StockItem,
    User,
)


STATUS_PL = {AVAILABLE: "dostępny", RESERVED: "zarezerwowany", CONSUMED: "zużyty", "DISCARDED": "wycofany"}


def _lock_plan(db: Session, user: User, plan_id: int):
    plan, access = load_scoped(db, user, CuttingPlan, plan_id,
                               lambda p: p.project.workshop_id, "plan", for_update=True)
    project = db.scalar(select(Project).where(Project.id == plan.project_id).with_for_update())
    return plan, project, access


def _lock_stock(db: Session, ids: list[int]) -> list[StockItem]:
    return list(db.scalars(
        select(StockItem).where(StockItem.id.in_(ids)).order_by(StockItem.id).with_for_update()
    ))


def _ensure_current(plan: CuttingPlan, project: Project) -> None:
    if plan.project_revision != project.revision:
        raise Conflict(
            "Plan jest nieaktualny – zapotrzebowanie lub parametry projektu zmieniły się. "
            "Wygeneruj plan ponownie.",
            code="STALE_PLAN",
        )


def reserve_plan(db: Session, user: User, plan_id: int) -> CuttingPlan:
    plan, project, access = _lock_plan(db, user, plan_id)
    access.require_owner()
    if plan.status == PLAN_RESERVED:
        return plan  # ponowienie tego samego żądania – bez zmian
    if plan.status != PLAN_DRAFT:
        raise Conflict("Plan został już wykonany.", code="PLAN_NOT_DRAFT")
    _ensure_current(plan, project)

    ids = sorted(bar.stock_item_id for bar in plan.bars)
    stock = _lock_stock(db, ids)
    unavailable = [s for s in stock if s.status != AVAILABLE]
    if len(stock) != len(ids) or unavailable:
        details = [f"Odcinek #{s.id} ({s.length_mm} mm) jest {STATUS_PL.get(s.status, s.status)}"
                   for s in unavailable]
        raise Conflict(
            "Część odcinków z planu nie jest już dostępna (zarezerwowana lub zużyta). "
            "Wygeneruj plan ponownie.",
            code="STOCK_UNAVAILABLE",
            problems=details,
        )
    result = db.execute(
        update(StockItem)
        .where(StockItem.id.in_(ids), StockItem.status == AVAILABLE)
        .values(status=RESERVED, reserved_plan_id=plan.id)
    )
    if result.rowcount != len(ids):  # pragma: no cover – chronione blokadą powyżej
        db.rollback()
        raise Conflict("Konflikt rezerwacji – spróbuj ponownie.", code="STOCK_UNAVAILABLE")
    plan.status = PLAN_RESERVED
    plan.reserved_at = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Projekt ma już zarezerwowany lub wykonany plan.", code="PROJECT_LOCKED") from exc
    return plan


def release_plan(db: Session, user: User, plan_id: int) -> CuttingPlan:
    plan, _project, access = _lock_plan(db, user, plan_id)
    access.require_owner()
    if plan.status == PLAN_DRAFT:
        return plan
    if plan.status != PLAN_RESERVED:
        raise Conflict("Nie można zwolnić rezerwacji wykonanego planu.", code="PLAN_NOT_RESERVED")
    _lock_stock(db, sorted(bar.stock_item_id for bar in plan.bars))
    db.execute(
        update(StockItem)
        .where(StockItem.reserved_plan_id == plan.id, StockItem.status == RESERVED)
        .values(status=AVAILABLE, reserved_plan_id=None)
    )
    plan.status = PLAN_DRAFT
    plan.reserved_at = None
    db.commit()
    return plan


def create_remnants(db: Session, plan: CuttingPlan, execution: PlanExecution) -> list[StockItem]:
    """Użyteczne pozostałości wracają do magazynu jako nowe odcinki z pochodzeniem."""
    remnants = []
    for bar in plan.bars:
        if not bar.usable_remnant:
            continue
        src = bar.stock_item
        remnant = StockItem(
            workshop_id=src.workshop_id,
            material_spec_id=src.material_spec_id,
            length_mm=bar.remainder_mm,
            status=AVAILABLE,
            is_remnant=True,
            label=f"Resztka z odcinka #{src.id} (plan #{plan.id})",
            parent_stock_id=src.id,
            source_execution_id=execution.id,
        )
        db.add(remnant)
        remnants.append(remnant)
    db.flush()
    return remnants


def execute_plan(db: Session, user: User, plan_id: int) -> tuple[CuttingPlan, list[StockItem], bool]:
    """Zwraca (plan, resztki, already_executed). Ponowienie nie zużywa materiału drugi raz."""
    plan, project, _access = _lock_plan(db, user, plan_id)  # właściciel i operator
    if plan.status == PLAN_EXECUTED:
        return plan, list(plan.execution.remnants), True
    if plan.status != PLAN_RESERVED:
        raise Conflict("Najpierw zarezerwuj materiał dla planu.", code="PLAN_NOT_RESERVED")
    _ensure_current(plan, project)

    ids = sorted(bar.stock_item_id for bar in plan.bars)
    stock = _lock_stock(db, ids)
    if len(stock) != len(ids) or any(s.status != RESERVED or s.reserved_plan_id != plan.id for s in stock):
        raise Conflict("Rezerwacja planu jest niespójna – zwolnij ją i wygeneruj plan ponownie.",
                       code="RESERVATION_INCONSISTENT")

    now = datetime.now(UTC)
    execution = PlanExecution(plan_id=plan.id, executed_by_id=user.id)
    db.add(execution)
    db.flush()
    db.execute(
        update(StockItem)
        .where(StockItem.id.in_(ids), StockItem.reserved_plan_id == plan.id)
        .values(status=CONSUMED, reserved_plan_id=None, consumed_at=now)
    )
    remnants = create_remnants(db, plan, execution)
    plan.status = PLAN_EXECUTED
    plan.executed_at = now
    db.commit()  # wszystko albo nic
    db.refresh(plan)
    return plan, remnants, False
