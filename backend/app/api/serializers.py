"""Zamiana modeli ORM na schematy odpowiedzi."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.domain import optimizer as opt
from app.models import CuttingPlan, DemandItem, MaterialSpec, Project, StockItem, User
from app.services.planning import project_state, spec_label


def spec_out(spec: MaterialSpec) -> schemas.MaterialSpecOut:
    return schemas.MaterialSpecOut(id=spec.id, material=spec.material, section=spec.section,
                                   label=spec_label(spec))


def stock_out(s: StockItem) -> schemas.StockOut:
    return schemas.StockOut(
        id=s.id, material_spec_id=s.material_spec_id, spec_label=spec_label(s.spec),
        length_mm=s.length_mm, status=s.status, is_remnant=s.is_remnant, label=s.label,
        reserved_plan_id=s.reserved_plan_id, parent_stock_id=s.parent_stock_id,
        source_execution_id=s.source_execution_id,
        source_plan_id=None,
        created_at=s.created_at, consumed_at=s.consumed_at,
    )


def stock_out_many(db: Session, items: list[StockItem]) -> list[schemas.StockOut]:
    from app.models import PlanExecution

    exec_ids = {s.source_execution_id for s in items if s.source_execution_id}
    plan_of_exec = dict(
        db.execute(select(PlanExecution.id, PlanExecution.plan_id).where(PlanExecution.id.in_(exec_ids))).all()
    ) if exec_ids else {}
    out = []
    for s in items:
        o = stock_out(s)
        o.source_plan_id = plan_of_exec.get(s.source_execution_id)
        out.append(o)
    return out


def demand_out(d: DemandItem) -> schemas.DemandOut:
    return schemas.DemandOut(id=d.id, material_spec_id=d.material_spec_id, spec_label=spec_label(d.spec),
                             length_mm=d.length_mm, quantity=d.quantity, label=d.label)


def project_out(db: Session, p: Project) -> schemas.ProjectOut:
    state, active_id = project_state(db, p)
    return schemas.ProjectOut(
        id=p.id, workshop_id=p.workshop_id, name=p.name, kerf_mm=p.kerf_mm,
        min_remnant_mm=p.min_remnant_mm, revision=p.revision, state=state, active_plan_id=active_id,
        created_at=p.created_at, demand_items=[demand_out(d) for d in p.demand_items],
    )


def plan_out(db: Session, plan: CuttingPlan) -> schemas.PlanOut:
    execution = None
    if plan.execution is not None:
        executor = db.get(User, plan.execution.executed_by_id)
        execution = schemas.ExecutionOut(
            id=plan.execution.id, executed_at=plan.execution.executed_at,
            executed_by=executor.full_name if executor else "?",
            remnant_stock_ids=[r.id for r in plan.execution.remnants],
        )
    bars = []
    for bar in plan.bars:
        s = bar.stock_item
        bars.append(schemas.PlanBarOut(
            stock_item_id=s.id, spec_label=spec_label(s.spec), stock_length_mm=bar.stock_length_mm,
            stock_is_remnant=s.is_remnant, stock_label=s.label, cut_count=bar.cut_count,
            kerf_loss_mm=bar.kerf_loss_mm, remainder_mm=bar.remainder_mm,
            usable_remnant=bar.usable_remnant,
            pieces=[schemas.PlanPieceOut(demand_item_id=p.demand_item_id, length_mm=p.length_mm,
                                         label=p.label) for p in bar.pieces],
        ))
    return schemas.PlanOut(
        id=plan.id, project_id=plan.project_id, run_id=plan.run_id, method=plan.method,
        status=plan.status, solver_status=plan.solver_status,
        is_current=plan.project_revision == plan.project.revision,
        project_revision=plan.project_revision, kerf_mm=plan.kerf_mm,
        min_remnant_mm=plan.min_remnant_mm, total_stock_mm=plan.total_stock_mm,
        stock_count=plan.stock_count, pieces_mm=plan.pieces_mm, kerf_loss_mm=plan.kerf_loss_mm,
        usable_remnant_mm=plan.usable_remnant_mm, scrap_mm=plan.scrap_mm,
        waste_mm=plan.kerf_loss_mm + plan.scrap_mm, lower_bound_mm=plan.lower_bound_mm,
        nodes=plan.nodes, elapsed_ms=plan.elapsed_ms, created_at=plan.created_at,
        reserved_at=plan.reserved_at, executed_at=plan.executed_at, bars=bars, execution=execution,
    )


def optimize_out(db: Session, result: dict) -> schemas.OptimizeOut:
    plans = result["plans"]
    outs = {}
    for key in ("greedy", "branch_and_bound"):
        r: opt.Result = result[key]
        plan = plans.get(r.method)
        outs[key] = schemas.MethodResultOut(
            method=r.method, status=r.status, plan=plan_out(db, plan) if plan else None,
            unplaced_count=len(r.unplaced), nodes=r.nodes, elapsed_ms=r.elapsed_ms,
        )
    g, b = plans.get(opt.GREEDY), plans.get(opt.BRANCH_AND_BOUND)
    if g and b:
        saved = g.total_stock_mm - b.total_stock_mm
        bars = g.stock_count - b.stock_count
        waste = (g.kerf_loss_mm + g.scrap_mm) - (b.kerf_loss_mm + b.scrap_mm)
        if saved > 0 or (saved == 0 and bars > 0):
            verdict = (f"Branch and bound zużywa o {saved} mm materiału mniej "
                       f"i {bars} odcinków mniej niż heurystyka.")
        else:
            verdict = "Obie metody dały plan o tej samej wartości funkcji celu."
        comparison = schemas.ComparisonOut(stock_saved_mm=saved, bars_saved=bars, waste_saved_mm=waste,
                                           verdict=verdict)
    elif b:
        comparison = schemas.ComparisonOut(
            stock_saved_mm=None, bars_saved=None, waste_saved_mm=None,
            verdict="Heurystyka nie znalazła planu, branch and bound znalazł plan pokrywający całe zapotrzebowanie.",
        )
    else:
        comparison = schemas.ComparisonOut(
            stock_saved_mm=None, bars_saved=None, waste_saved_mm=None,
            verdict="Żadna metoda nie znalazła planu pokrywającego całe zapotrzebowanie.",
        )
    return schemas.OptimizeOut(
        run_id=result["run_id"], greedy=outs["greedy"], branch_and_bound=outs["branch_and_bound"],
        comparison=comparison, shortages=[schemas.ShortageOut(**s) for s in result["shortages"]],
    )
