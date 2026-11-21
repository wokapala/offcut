"""Projekty cięcia, zapotrzebowanie, optymalizacja i przepływ planu."""

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import schemas
from app.api.serializers import optimize_out, plan_out, project_out, stock_out_many
from app.db import get_db
from app.events import DomainEvent, publish
from app.deps import get_current_user, load_scoped, workshop_access
from app.errors import NotFound
from app.models import CuttingPlan, DemandItem, MaterialSpec, Project, StockItem, User, WorkshopEvent
from app.services import planning, workflow

router = APIRouter(prefix="/api", tags=["projects"])

CONFLICT = {409: {"description": "Konflikt stanu (np. projekt zablokowany rezerwacją)"}}


def _project(db: Session, user: User, project_id: int):
    return load_scoped(db, user, Project, project_id, lambda p: p.workshop_id, "projekt")


def _spec_check(db: Session, spec_id: int, workshop_id: int) -> None:
    spec = db.get(MaterialSpec, spec_id)
    if spec is None or spec.workshop_id != workshop_id:
        raise NotFound("Nie znaleziono specyfikacji materiału w tym warsztacie")


@router.get("/workshops/{workshop_id}/projects", response_model=list[schemas.ProjectListItem],
            summary="Lista projektów cięcia")
def list_projects(workshop_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workshop_access(db, user, workshop_id)
    projects = db.scalars(select(Project).where(Project.workshop_id == workshop_id).order_by(Project.id.desc()))
    out = []
    for p in projects:
        state, _ = planning.project_state(db, p)
        out.append(schemas.ProjectListItem(
            id=p.id, name=p.name, state=state, kerf_mm=p.kerf_mm, min_remnant_mm=p.min_remnant_mm,
            demand_lines=len(p.demand_items), piece_count=sum(d.quantity for d in p.demand_items),
            created_at=p.created_at,
        ))
    return out


@router.post("/workshops/{workshop_id}/projects", response_model=schemas.ProjectOut, status_code=201,
             summary="Nowy projekt cięcia z parametrami rzazu i progu resztki (właściciel)")
def create_project(workshop_id: int, body: schemas.ProjectCreateIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    workshop_access(db, user, workshop_id).require_owner()
    project = Project(workshop_id=workshop_id, name=body.name, kerf_mm=body.kerf_mm,
                      min_remnant_mm=body.min_remnant_mm, revision=1, created_by_id=user.id)
    db.add(project)
    db.commit()
    return project_out(db, project)


@router.get("/projects/{project_id}", response_model=schemas.ProjectOut,
            summary="Projekt z zapotrzebowaniem i stanem (OPEN / RESERVED / EXECUTED)")
def get_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = _project(db, user, project_id)
    return project_out(db, project)


@router.patch("/projects/{project_id}", response_model=schemas.ProjectOut, responses=CONFLICT,
              summary="Zmiana nazwy lub parametrów (zmiana rzazu/progu unieważnia stare plany)")
def update_project(project_id: int, body: schemas.ProjectUpdateIn, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    project, access = _project(db, user, project_id)
    access.require_owner()
    if body.name is not None:
        project.name = body.name
    params = {k: v for k, v in body.model_dump(exclude_none=True).items() if k in ("kerf_mm", "min_remnant_mm")}
    if any(getattr(project, k) != v for k, v in params.items()):
        project = planning.lock_project_for_change(db, project.id)
        for k, v in params.items():
            setattr(project, k, v)
        planning.bump_revision(project)
    db.commit()
    return project_out(db, project)


@router.post("/projects/{project_id}/demand", response_model=schemas.ProjectOut, status_code=201,
             responses=CONFLICT, summary="Dodanie pozycji zapotrzebowania (unieważnia stare plany)")
def add_demand(project_id: int, body: schemas.DemandIn, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    project, access = _project(db, user, project_id)
    access.require_owner()
    _spec_check(db, body.material_spec_id, project.workshop_id)
    project = planning.lock_project_for_change(db, project.id)
    db.add(DemandItem(project_id=project.id, **body.model_dump()))
    planning.bump_revision(project)
    db.commit()
    db.refresh(project)
    return project_out(db, project)


def _demand(db: Session, user: User, demand_id: int):
    item, access = load_scoped(db, user, DemandItem, demand_id, lambda d: d.project.workshop_id,
                               "pozycja zapotrzebowania")
    access.require_owner()
    return item


@router.patch("/demand/{demand_id}", response_model=schemas.ProjectOut, responses=CONFLICT,
              summary="Zmiana pozycji zapotrzebowania (unieważnia stare plany)")
def update_demand(demand_id: int, body: schemas.DemandUpdateIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    item = _demand(db, user, demand_id)
    changes = body.model_dump(exclude_unset=True)
    if "material_spec_id" in changes:
        _spec_check(db, changes["material_spec_id"], item.project.workshop_id)
    project = planning.lock_project_for_change(db, item.project_id)
    for k, v in changes.items():
        if v is not None or k == "label":
            setattr(item, k, v)
    planning.bump_revision(project)
    db.commit()
    db.refresh(project)
    return project_out(db, project)


@router.delete("/demand/{demand_id}", response_model=schemas.ProjectOut, responses=CONFLICT,
               summary="Usunięcie pozycji zapotrzebowania (unieważnia stare plany)")
def delete_demand(demand_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    item = _demand(db, user, demand_id)
    project = planning.lock_project_for_change(db, item.project_id)
    db.delete(item)
    planning.bump_revision(project)
    db.commit()
    db.refresh(project)
    return project_out(db, project)


@router.post("/projects/{project_id}/optimize", response_model=schemas.OptimizeOut, responses={
    **CONFLICT, 422: {"description": "Brak zapotrzebowania lub zbyt duży problem"}},
    summary="Optymalizacja rozkroju: heurystyka FFD i branch and bound dla tych samych danych")
def optimize(project_id: int, background: BackgroundTasks, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    project, access = _project(db, user, project_id)
    access.require_owner()
    out = optimize_out(db, planning.optimize_project(db, project, user))
    g, b = out.greedy, out.branch_and_bound
    summary = (f"FFD {g.plan.total_stock_mm} mm, B&B {b.plan.total_stock_mm} mm ({b.status})"
               if g.plan and b.plan else f"B&B: {b.status}")
    publish(background, DomainEvent("OPTIMIZATION_FINISHED", project.workshop_id, user.id,
                                    f"Optymalizacja projektu „{project.name}”: {summary}",
                                    {"project_id": project.id, "run_id": out.run_id}))
    return out


@router.get("/projects/{project_id}/plans", response_model=list[schemas.PlanOut],
            summary="Historia planów projektu (z flagą is_current)")
def list_plans(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project, _ = _project(db, user, project_id)
    plans = db.scalars(select(CuttingPlan).where(CuttingPlan.project_id == project.id)
                       .order_by(CuttingPlan.id.desc()))
    return [plan_out(db, p) for p in plans]


@router.post("/projects/{project_id}/plans/manual", response_model=schemas.PlanOut, status_code=201,
             responses={**CONFLICT, 422: {"description": "Plan nie przeszedł walidacji bilansu"}},
             summary="Plan ręczny – sprawdzany tym samym walidatorem co wyniki algorytmów")
def manual_plan(project_id: int, body: schemas.ManualPlanIn, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    project, access = _project(db, user, project_id)
    access.require_owner()
    plan = planning.create_manual_plan(db, project, user,
                                       [(b.stock_item_id, b.demand_item_ids) for b in body.bars])
    return plan_out(db, plan)


# --- Plany ---------------------------------------------------------------------------


def _plan_event(background: BackgroundTasks, event_type: str, plan: CuttingPlan, user: User, message: str,
                data: dict | None = None) -> None:
    publish(background, DomainEvent(event_type, plan.project.workshop_id, user.id,
                                    f"{message} (projekt „{plan.project.name}”)",
                                    {"plan_id": plan.id, "project_id": plan.project_id, **(data or {})}))


@router.get("/plans/{plan_id}", response_model=schemas.PlanOut,
            summary="Szczegóły planu: odcinki, elementy, rzaz, resztki, statystyki")
def get_plan(plan_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan, _ = load_scoped(db, user, CuttingPlan, plan_id, lambda p: p.project.workshop_id, "plan")
    return plan_out(db, plan)


@router.post("/plans/{plan_id}/reserve", response_model=schemas.PlanOut, responses=CONFLICT,
             summary="Rezerwacja odcinków planu (właściciel). 409 gdy odcinek zajęty lub plan nieaktualny")
def reserve(plan_id: int, background: BackgroundTasks, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    plan = workflow.reserve_plan(db, user, plan_id)
    _plan_event(background, "PLAN_RESERVED", plan, user, f"Zarezerwowano materiał dla planu #{plan.id}")
    return plan_out(db, plan)


@router.post("/plans/{plan_id}/release", response_model=schemas.PlanOut, responses=CONFLICT,
             summary="Zwolnienie rezerwacji: plan wraca do DRAFT, odcinki do AVAILABLE")
def release(plan_id: int, background: BackgroundTasks, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    plan = workflow.release_plan(db, user, plan_id)
    _plan_event(background, "PLAN_RELEASED", plan, user, f"Zwolniono rezerwację planu #{plan.id}")
    return plan_out(db, plan)


@router.post("/plans/{plan_id}/execute", response_model=schemas.ExecuteOut, responses=CONFLICT,
             summary="Zatwierdzenie wykonania (właściciel lub operator). Idempotentne przy ponowieniu")
def execute(plan_id: int, background: BackgroundTasks, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    plan, remnants, already = workflow.execute_plan(db, user, plan_id)
    if not already:  # ponowienie żądania nie generuje drugiego zdarzenia
        lengths = ", ".join(f"{r.length_mm} mm" for r in remnants) or "brak"
        _plan_event(background, "PLAN_EXECUTED", plan, user,
                    f"Wykonano plan #{plan.id}; nowe resztki: {lengths}",
                    {"remnant_stock_ids": [r.id for r in remnants]})
    return schemas.ExecuteOut(plan=plan_out(db, plan), already_executed=already,
                              remnants=stock_out_many(db, remnants))


@router.get("/workshops/{workshop_id}/summary", summary="Liczniki magazynu dla nagłówka UI")
def summary(workshop_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    workshop_access(db, user, workshop_id)
    rows = db.execute(
        select(StockItem.status, func.count(), func.coalesce(func.sum(StockItem.length_mm), 0))
        .where(StockItem.workshop_id == workshop_id).group_by(StockItem.status)
    ).all()
    return {status: {"count": c, "length_mm": int(s)} for status, c, s in rows}


@router.get("/workshops/{workshop_id}/events", response_model=schemas.EventPage,
            summary="Dziennik zdarzeń warsztatu – paginacja (limit/offset) i filtrowanie po typie")
def list_events(
    workshop_id: int,
    type: schemas.EventType | None = Query(None, description="Filtr po typie zdarzenia"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workshop_access(db, user, workshop_id)
    stmt = select(WorkshopEvent).where(WorkshopEvent.workshop_id == workshop_id)
    if type is not None:
        stmt = stmt.where(WorkshopEvent.type == type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(WorkshopEvent.created_at.desc(), WorkshopEvent.id.desc())
                      .limit(limit).offset(offset))
    items = [schemas.EventOut(id=e.id, type=e.type, message=e.message,
                              actor=e.actor.full_name if e.actor else None, data=e.data,
                              created_at=e.created_at) for e in rows]
    return schemas.EventPage(items=items, total=total, limit=limit, offset=offset)
