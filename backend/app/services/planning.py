"""Planowanie: uruchomienie optymalizacji, plan ręczny i zapis planu.

Każdy plan – z heurystyki, z branch and bound i ręczny – przechodzi przez ten sam
``validate_plan`` i ``bar_balance`` (app.domain.cutting), więc statystyki, schemat
i późniejsze zmiany magazynu wynikają z jednego modelu rzazu.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain import optimizer as opt
from app.domain.cutting import (
    BarAssignment,
    DemandInfo,
    PlanSummary,
    PlanValidationError,
    StockInfo,
    validate_plan,
)
from app.errors import Conflict, Unprocessable
from app.models import (
    AVAILABLE,
    METHOD_MANUAL,
    PLAN_DRAFT,
    PLAN_EXECUTED,
    PLAN_RESERVED,
    CuttingPlan,
    DemandItem,
    MaterialSpec,
    PlanBar,
    PlanPiece,
    Project,
    StockItem,
    User,
)


def spec_label(spec: MaterialSpec) -> str:
    return f"{spec.material} {spec.section}"


def active_plan(db: Session, project_id: int) -> CuttingPlan | None:
    return db.scalar(
        select(CuttingPlan).where(
            CuttingPlan.project_id == project_id,
            CuttingPlan.status.in_([PLAN_RESERVED, PLAN_EXECUTED]),
        )
    )


def project_state(db: Session, project: Project) -> tuple[str, int | None]:
    plan = active_plan(db, project.id)
    if plan is None:
        return "OPEN", None
    return ("RESERVED" if plan.status == PLAN_RESERVED else "EXECUTED"), plan.id


def lock_project_for_change(db: Session, project_id: int) -> Project:
    """Blokuje wiersz projektu i sprawdza, że można zmieniać zapotrzebowanie/parametry."""
    # populate_existing: projekt mógł być wczytany wcześniej w tej sesji bez blokady – po uzyskaniu
    # blokady musimy widzieć wersję zatwierdzoną przez transakcję, na którą czekaliśmy.
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update()
                        .execution_options(populate_existing=True))
    plan = active_plan(db, project_id)
    if plan is not None:
        if plan.status == PLAN_RESERVED:
            raise Conflict(
                f"Projekt ma zarezerwowany plan #{plan.id}. Zwolnij rezerwację, aby zmienić dane.",
                code="PROJECT_LOCKED",
            )
        raise Conflict("Projekt został już wykonany – nie można go zmieniać.", code="PROJECT_LOCKED")
    return project


def bump_revision(project: Project) -> None:
    """Zmiana danych wejściowych unieważnia wcześniej wygenerowane plany."""
    project.revision += 1


# ---------------------------------------------------------------------------
# Zapis planu (wspólny dla wszystkich metod)
# ---------------------------------------------------------------------------


def _demand_infos(project: Project) -> dict[int, DemandInfo]:
    return {
        d.id: DemandInfo(d.id, d.material_spec_id, d.length_mm, d.quantity)
        for d in project.demand_items
    }


def persist_plan(
    db: Session,
    project: Project,
    user: User,
    *,
    method: str,
    solver_status: str,
    assignments: list[BarAssignment],
    candidates: dict[int, StockItem],
    snapshot: dict,
    run_id: str | None = None,
    nodes: int = 0,
    elapsed_ms: int = 0,
    lower_bound: int | None = None,
) -> CuttingPlan:
    stock_infos = {s.id: StockInfo(s.id, s.material_spec_id, s.length_mm) for s in candidates.values()}
    summary: PlanSummary = validate_plan(
        assignments, stock_infos, _demand_infos(project), project.kerf_mm, project.min_remnant_mm
    )
    demand_by_id = {d.id: d for d in project.demand_items}
    plan = CuttingPlan(
        project_id=project.id,
        project_revision=project.revision,
        run_id=run_id,
        method=method,
        status=PLAN_DRAFT,
        solver_status=solver_status,
        kerf_mm=project.kerf_mm,
        min_remnant_mm=project.min_remnant_mm,
        total_stock_mm=summary.total_stock_length,
        stock_count=summary.stock_count,
        pieces_mm=summary.pieces_length,
        kerf_loss_mm=summary.kerf_loss,
        usable_remnant_mm=summary.usable_remnant_length,
        scrap_mm=summary.scrap_length,
        lower_bound_mm=lower_bound,
        nodes=nodes,
        elapsed_ms=elapsed_ms,
        input_snapshot=snapshot,
        created_by_id=user.id,
    )
    for pos, (assignment, balance) in enumerate(summary.bars):
        bar = PlanBar(
            stock_item_id=assignment.stock_id,
            position=pos,
            stock_length_mm=balance.stock_length,
            cut_count=balance.cut_count,
            kerf_loss_mm=balance.kerf_loss,
            remainder_mm=balance.remainder,
            usable_remnant=balance.usable_remnant,
        )
        for ppos, did in enumerate(assignment.demand_ids):
            d = demand_by_id[did]
            bar.pieces.append(PlanPiece(demand_item_id=did, position=ppos, length_mm=d.length_mm,
                                        label=d.label))
        plan.bars.append(bar)
    db.add(plan)
    db.flush()
    return plan


def _snapshot(project: Project, candidates: list[StockItem], limits: opt.Limits | None) -> dict:
    snap = {
        "project_revision": project.revision,
        "kerf_mm": project.kerf_mm,
        "min_remnant_mm": project.min_remnant_mm,
        "demand": [
            {"id": d.id, "spec_id": d.material_spec_id, "length_mm": d.length_mm, "quantity": d.quantity}
            for d in project.demand_items
        ],
        "stock_candidates": [
            {"id": s.id, "spec_id": s.material_spec_id, "length_mm": s.length_mm} for s in candidates
        ],
    }
    if limits:
        snap["limits"] = {"max_nodes": limits.max_nodes, "time_limit_s": limits.time_limit_s}
    return snap


# ---------------------------------------------------------------------------
# Optymalizacja
# ---------------------------------------------------------------------------


def _candidate_stock(db: Session, project: Project, pieces_per_spec: dict[int, int]) -> list[StockItem]:
    """Dostępne odcinki zgodne materiałowo. Z odcinków o tej samej długości bierzemy najwyżej
    tyle, ile elementów danej specyfikacji (więcej nie może zostać użytych) – redukcja bezstratna."""
    rows = db.scalars(
        select(StockItem)
        .where(
            StockItem.workshop_id == project.workshop_id,
            StockItem.material_spec_id.in_(pieces_per_spec.keys()),
            StockItem.status == AVAILABLE,
        )
        .order_by(StockItem.length_mm, StockItem.id)
    ).all()
    taken: dict[tuple[int, int], int] = defaultdict(int)
    out = []
    for s in rows:
        key = (s.material_spec_id, s.length_mm)
        if taken[key] < pieces_per_spec[s.material_spec_id]:
            taken[key] += 1
            out.append(s)
    return out


def _shortage(spec: MaterialSpec, pieces: list[opt.Piece], stocks: list[StockItem], status: str) -> dict:
    longest_piece = max(p.length for p in pieces)
    longest_stock = max((s.length_mm for s in stocks), default=0)
    pieces_mm = sum(p.length for p in pieces)
    available_mm = sum(s.length_mm for s in stocks)
    if longest_piece > longest_stock:
        msg = (f"{spec_label(spec)}: element {longest_piece} mm jest dłuższy niż najdłuższy "
               f"dostępny odcinek ({longest_stock} mm).")
    elif status == opt.NO_SOLUTION_IN_LIMIT:
        msg = f"{spec_label(spec)}: nie znaleziono planu w limicie obliczeń."
    else:
        msg = (f"{spec_label(spec)}: dostępnego materiału nie wystarczy na całe zapotrzebowanie "
               f"(potrzeba {pieces_mm} mm elementów + rzaz, dostępne {available_mm} mm).")
    return {
        "material_spec_id": spec.id,
        "spec_label": spec_label(spec),
        "piece_count": len(pieces),
        "pieces_mm": pieces_mm,
        "longest_piece_mm": longest_piece,
        "available_count": len(stocks),
        "available_mm": available_mm,
        "longest_available_mm": longest_stock,
        "message": msg,
    }


def optimize_project(db: Session, project: Project, user: User) -> dict:
    settings = get_settings()
    project = lock_project_for_change(db, project.id)
    demand: list[DemandItem] = list(project.demand_items)
    if not demand:
        raise Unprocessable("Dodaj co najmniej jedną pozycję zapotrzebowania.", code="EMPTY_DEMAND")
    total = sum(d.quantity for d in demand)
    if total > settings.max_pieces_per_project:
        raise Unprocessable(
            f"Zbyt duży problem: {total} elementów (limit {settings.max_pieces_per_project}).",
            code="PROBLEM_TOO_LARGE",
        )

    pieces_by_spec: dict[int, list[opt.Piece]] = defaultdict(list)
    for d in demand:
        pieces_by_spec[d.material_spec_id].extend(opt.Piece(d.id, d.length_mm) for _ in range(d.quantity))
    candidates = _candidate_stock(db, project, {k: len(v) for k, v in pieces_by_spec.items()})
    if len(candidates) > settings.max_stock_candidates:
        raise Unprocessable(
            f"Zbyt wiele odcinków-kandydatów ({len(candidates)}, limit {settings.max_stock_candidates}).",
            code="PROBLEM_TOO_LARGE",
        )
    stock_by_spec: dict[int, list[StockItem]] = defaultdict(list)
    for s in candidates:
        stock_by_spec[s.material_spec_id].append(s)

    groups = [
        opt.Group(spec_id, tuple(opt.Stock(s.id, s.length_mm) for s in stock_by_spec[spec_id]), tuple(ps))
        for spec_id, ps in sorted(pieces_by_spec.items())
    ]
    limits = opt.Limits(settings.optimizer_max_nodes, settings.optimizer_time_limit_s)
    greedy, bnb = opt.optimize(groups, project.kerf_mm, limits)

    run_id = str(uuid.uuid4())
    snapshot = _snapshot(project, candidates, limits)
    by_id = {s.id: s for s in candidates}
    plans: dict[str, CuttingPlan | None] = {}
    for result in (greedy, bnb):
        if not result.complete:
            plans[result.method] = None
            continue
        assignments = [
            BarAssignment(b.stock.id, tuple(p.demand_id for p in b.pieces)) for b in result.bars
        ]
        plans[result.method] = persist_plan(
            db, project, user,
            method=result.method, solver_status=result.status, assignments=assignments,
            candidates=by_id, snapshot=snapshot, run_id=run_id, nodes=result.nodes,
            elapsed_ms=result.elapsed_ms, lower_bound=result.lower_bound,
        )

    specs = {s.id: s for s in db.scalars(select(MaterialSpec).where(MaterialSpec.id.in_(pieces_by_spec)))}
    shortages = [
        _shortage(specs[part.spec_id], pieces_by_spec[part.spec_id], stock_by_spec[part.spec_id], part.status)
        for part in bnb.parts
        if not part.complete
    ]
    db.commit()
    return {
        "run_id": run_id,
        "greedy": greedy,
        "branch_and_bound": bnb,
        "plans": plans,
        "shortages": shortages,
    }


def create_manual_plan(db: Session, project: Project, user: User, bars: list[tuple[int, list[int]]]) -> CuttingPlan:
    project = lock_project_for_change(db, project.id)
    stock_ids = {sid for sid, _ in bars}
    candidates = {
        s.id: s
        for s in db.scalars(
            select(StockItem).where(
                StockItem.id.in_(stock_ids),
                StockItem.workshop_id == project.workshop_id,
                StockItem.status == AVAILABLE,
            )
        )
    }
    assignments = [BarAssignment(sid, tuple(dids)) for sid, dids in bars]
    try:
        plan = persist_plan(
            db, project, user, method=METHOD_MANUAL, solver_status="MANUAL",
            assignments=assignments, candidates=candidates,
            snapshot=_snapshot(project, list(candidates.values()), None),
        )
    except PlanValidationError as exc:
        raise Unprocessable("Plan ręczny jest niepoprawny", code="INVALID_PLAN", problems=exc.problems) from exc
    db.commit()
    return plan
