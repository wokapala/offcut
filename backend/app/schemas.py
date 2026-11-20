"""Kontrakt REST API (wejście i wyjście). Długości w milimetrach, liczby całkowite."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ShortName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Length = Annotated[int, Field(gt=0, le=100_000, description="Długość w mm (liczba całkowita > 0)")]


def _normalize_email(value: str) -> str:
    value = value.strip().lower()
    local, _, domain = value.partition("@")
    if not local or "." not in domain or " " in value or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Nieprawidłowy adres e-mail")
    return value


Email = Annotated[str, StringConstraints(max_length=254), AfterValidator(_normalize_email)]
Password = Annotated[str, StringConstraints(min_length=8, max_length=128)]
Role = Literal["OWNER", "OPERATOR"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Auth --------------------------------------------------------------------


class RegisterIn(BaseModel):
    email: Email
    password: Password
    full_name: Name
    workshop_name: Name = Field(description="Nazwa nowego warsztatu – rejestrujący zostaje właścicielem")


class LoginIn(BaseModel):
    email: Email
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class MembershipOut(BaseModel):
    workshop_id: int
    workshop_name: str
    role: Role


class MeOut(BaseModel):
    id: int
    email: str
    full_name: str
    memberships: list[MembershipOut]


class LoginOut(BaseModel):
    user: MeOut
    csrf_token: str = Field(description="Wysyłaj w nagłówku X-CSRF-Token przy POST/PATCH/DELETE")


# --- Warsztat ----------------------------------------------------------------


class MemberIn(BaseModel):
    email: Email
    full_name: Name
    password: Password = Field(description="Hasło nowego konta (tworzone jest zawsze nowe konto)")
    role: Role = "OPERATOR"


class MemberOut(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: Role


# --- Materiały i magazyn -------------------------------------------------------


class MaterialSpecIn(BaseModel):
    material: ShortName = Field(examples=["Sosna"])
    section: ShortName = Field(examples=["40x20 mm"])


class MaterialSpecOut(ORM):
    id: int
    material: str
    section: str
    label: str


class StockCreateIn(BaseModel):
    material_spec_id: int
    length_mm: Length
    quantity: Annotated[int, Field(ge=1, le=100)] = Field(
        1, description="Ile fizycznych odcinków utworzyć – każdy dostaje własne ID"
    )
    is_remnant: bool = False
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None


StockStatus = Literal["AVAILABLE", "RESERVED", "CONSUMED", "DISCARDED"]


class StockOut(BaseModel):
    id: int
    material_spec_id: int
    spec_label: str
    length_mm: int
    status: StockStatus
    is_remnant: bool
    label: str | None
    reserved_plan_id: int | None
    parent_stock_id: int | None
    source_execution_id: int | None
    source_plan_id: int | None = Field(None, description="Plan, z którego wykonania powstała resztka")
    created_at: datetime
    consumed_at: datetime | None


# --- Projekty i zapotrzebowanie --------------------------------------------------


class ProjectCreateIn(BaseModel):
    name: Name
    kerf_mm: Annotated[int, Field(ge=0, le=50)] = Field(3, description="Szerokość rzazu (mm)")
    min_remnant_mm: Annotated[int, Field(ge=0, le=100_000)] = Field(
        300, description="Minimalna długość użytecznej resztki (mm)"
    )


class ProjectUpdateIn(BaseModel):
    name: Name | None = None
    kerf_mm: Annotated[int, Field(ge=0, le=50)] | None = None
    min_remnant_mm: Annotated[int, Field(ge=0, le=100_000)] | None = None


class DemandIn(BaseModel):
    material_spec_id: int
    length_mm: Length
    quantity: Annotated[int, Field(ge=1, le=500)]
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None


class DemandUpdateIn(BaseModel):
    material_spec_id: int | None = None
    length_mm: Length | None = None
    quantity: Annotated[int, Field(ge=1, le=500)] | None = None
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None


class DemandOut(BaseModel):
    id: int
    material_spec_id: int
    spec_label: str
    length_mm: int
    quantity: int
    label: str | None


ProjectState = Literal["OPEN", "RESERVED", "EXECUTED"]


class ProjectOut(BaseModel):
    id: int
    workshop_id: int
    name: str
    kerf_mm: int
    min_remnant_mm: int
    revision: int
    state: ProjectState
    active_plan_id: int | None
    created_at: datetime
    demand_items: list[DemandOut]


class ProjectListItem(BaseModel):
    id: int
    name: str
    state: ProjectState
    kerf_mm: int
    min_remnant_mm: int
    demand_lines: int
    piece_count: int
    created_at: datetime


# --- Plany ---------------------------------------------------------------------

PlanStatus = Literal["DRAFT", "RESERVED", "EXECUTED"]
Method = Literal["GREEDY", "BRANCH_AND_BOUND", "MANUAL"]
SolverStatus = Literal["HEURISTIC", "OPTIMAL", "BEST_FOUND", "INFEASIBLE", "NO_SOLUTION_IN_LIMIT",
                       "MANUAL"]


class PlanPieceOut(BaseModel):
    demand_item_id: int | None
    length_mm: int
    label: str | None


class PlanBarOut(BaseModel):
    stock_item_id: int
    spec_label: str
    stock_length_mm: int
    stock_is_remnant: bool
    stock_label: str | None
    cut_count: int
    kerf_loss_mm: int
    remainder_mm: int
    usable_remnant: bool
    pieces: list[PlanPieceOut]


class ExecutionOut(BaseModel):
    id: int
    executed_at: datetime
    executed_by: str
    remnant_stock_ids: list[int]


class PlanOut(BaseModel):
    id: int
    project_id: int
    run_id: str | None
    method: Method
    status: PlanStatus
    solver_status: SolverStatus
    is_current: bool = Field(description="False, gdy projekt zmienił się po wygenerowaniu planu")
    project_revision: int
    kerf_mm: int
    min_remnant_mm: int
    total_stock_mm: int
    stock_count: int
    pieces_mm: int
    kerf_loss_mm: int
    usable_remnant_mm: int
    scrap_mm: int
    waste_mm: int = Field(description="Odpad = rzaz + nieużyteczne pozostałości")
    lower_bound_mm: int | None
    nodes: int
    elapsed_ms: int
    created_at: datetime
    reserved_at: datetime | None
    executed_at: datetime | None
    bars: list[PlanBarOut]
    execution: ExecutionOut | None


class ShortageOut(BaseModel):
    material_spec_id: int
    spec_label: str
    piece_count: int
    pieces_mm: int
    longest_piece_mm: int
    available_count: int
    available_mm: int
    longest_available_mm: int
    message: str


class MethodResultOut(BaseModel):
    method: Method
    status: SolverStatus
    plan: PlanOut | None
    unplaced_count: int
    nodes: int
    elapsed_ms: int


class ComparisonOut(BaseModel):
    stock_saved_mm: int | None = Field(description="O ile mniej materiału zużywa B&B niż heurystyka")
    bars_saved: int | None
    waste_saved_mm: int | None
    verdict: str


class OptimizeOut(BaseModel):
    run_id: str
    greedy: MethodResultOut
    branch_and_bound: MethodResultOut
    comparison: ComparisonOut
    shortages: list[ShortageOut]


class ManualBarIn(BaseModel):
    stock_item_id: int
    demand_item_ids: Annotated[list[int], Field(min_length=1, max_length=500)]


class ManualPlanIn(BaseModel):
    bars: Annotated[list[ManualBarIn], Field(min_length=1, max_length=500)]


class ExecuteOut(BaseModel):
    plan: PlanOut
    already_executed: bool = Field(description="True przy ponowieniu – nic nie zużyto drugi raz")
    remnants: list[StockOut]
