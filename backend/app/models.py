"""Model relacyjny. Opis i diagram ERD: docs/ERD.md."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Role w warsztacie
OWNER = "OWNER"
OPERATOR = "OPERATOR"

# Stany fizycznego odcinka
AVAILABLE = "AVAILABLE"
RESERVED = "RESERVED"
CONSUMED = "CONSUMED"
DISCARDED = "DISCARDED"

# Stany planu: DRAFT -> RESERVED -> EXECUTED; RESERVED -> DRAFT (zwolnienie rezerwacji)
PLAN_DRAFT = "DRAFT"
PLAN_RESERVED = "RESERVED"
PLAN_EXECUTED = "EXECUTED"

METHOD_GREEDY = "GREEDY"
METHOD_BNB = "BRANCH_AND_BOUND"
METHOD_MANUAL = "MANUAL"


def _now_col():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = _now_col()

    memberships: Mapped[list[Membership]] = relationship(back_populates="user")


class Workshop(Base):
    __tablename__ = "workshops"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = _now_col()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "workshop_id", name="uq_membership_user_workshop"),
        CheckConstraint("role IN ('OWNER', 'OPERATOR')", name="ck_membership_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    workshop_id: Mapped[int] = mapped_column(
        ForeignKey("workshops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    workshop: Mapped[Workshop] = relationship()


class MaterialSpec(Base):
    """Specyfikacja: materiał + przekrój (np. sosna, 40x20 mm)."""

    __tablename__ = "material_specs"
    __table_args__ = (
        UniqueConstraint("workshop_id", "material", "section", name="uq_spec_workshop_material_section"),
        UniqueConstraint("id", "workshop_id", name="uq_spec_id_workshop"),  # cel złożonego FK
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(
        ForeignKey("workshops.id", ondelete="CASCADE"), nullable=False
    )
    material: Mapped[str] = mapped_column(String(80), nullable=False)
    section: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = _now_col()


class StockItem(Base):
    """Fizyczny odcinek w magazynie. Każdy ma własną tożsamość; resztka to też odcinek."""

    __tablename__ = "stock_items"
    __table_args__ = (
        # odcinek i jego specyfikacja muszą należeć do tego samego warsztatu
        ForeignKeyConstraint(
            ["material_spec_id", "workshop_id"],
            ["material_specs.id", "material_specs.workshop_id"],
            name="fk_stock_spec_same_workshop",
        ),
        CheckConstraint("length_mm > 0", name="ck_stock_length_positive"),
        CheckConstraint(
            "status IN ('AVAILABLE', 'RESERVED', 'CONSUMED', 'DISCARDED')", name="ck_stock_status"
        ),
        CheckConstraint(
            "(status = 'RESERVED') = (reserved_plan_id IS NOT NULL)", name="ck_stock_reservation_consistent"
        ),
        CheckConstraint("source_execution_id IS NULL OR is_remnant", name="ck_stock_execution_remnant"),
        Index("ix_stock_lookup", "workshop_id", "material_spec_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(
        ForeignKey("workshops.id", ondelete="CASCADE"), nullable=False
    )
    material_spec_id: Mapped[int] = mapped_column(Integer, nullable=False)
    length_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AVAILABLE)
    is_remnant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label: Mapped[str | None] = mapped_column(String(120))
    reserved_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("cutting_plans.id", name="fk_stock_reserved_plan", use_alter=True), index=True
    )
    parent_stock_id: Mapped[int | None] = mapped_column(ForeignKey("stock_items.id"))
    source_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("plan_executions.id", name="fk_stock_source_execution", use_alter=True)
    )
    created_at: Mapped[datetime] = _now_col()
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    spec: Mapped[MaterialSpec] = relationship(
        primaryjoin="StockItem.material_spec_id == MaterialSpec.id",
        foreign_keys="StockItem.material_spec_id",
        viewonly=True,
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("kerf_mm >= 0", name="ck_project_kerf_non_negative"),
        CheckConstraint("min_remnant_mm >= 0", name="ck_project_min_remnant_non_negative"),
        CheckConstraint("revision >= 1", name="ck_project_revision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(
        ForeignKey("workshops.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kerf_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    min_remnant_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    # Każda zmiana zapotrzebowania lub parametrów zwiększa rewizję – plany ze starszą
    # rewizją nie mogą być zarezerwowane ani wykonane.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _now_col()

    demand_items: Mapped[list[DemandItem]] = relationship(
        back_populates="project", order_by="DemandItem.id", cascade="all, delete-orphan"
    )


class DemandItem(Base):
    __tablename__ = "demand_items"
    __table_args__ = (
        CheckConstraint("length_mm > 0", name="ck_demand_length_positive"),
        CheckConstraint("quantity > 0", name="ck_demand_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    material_spec_id: Mapped[int] = mapped_column(ForeignKey("material_specs.id"), nullable=False)
    length_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))

    project: Mapped[Project] = relationship(back_populates="demand_items")
    spec: Mapped[MaterialSpec] = relationship()


class CuttingPlan(Base):
    __tablename__ = "cutting_plans"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'RESERVED', 'EXECUTED')", name="ck_plan_status"),
        CheckConstraint(
            "method IN ('GREEDY', 'BRANCH_AND_BOUND', 'MANUAL')", name="ck_plan_method"
        ),
        CheckConstraint("kerf_mm >= 0 AND min_remnant_mm >= 0", name="ck_plan_params"),
        CheckConstraint(
            "total_stock_mm = pieces_mm + kerf_loss_mm + usable_remnant_mm + scrap_mm",
            name="ck_plan_length_balance",
        ),
        # Projekt może mieć co najwyżej jeden plan zarezerwowany lub wykonany.
        Index(
            "uq_plan_one_active_per_project",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('RESERVED', 'EXECUTED')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)  # wspólne dla porównywanych metod
    method: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PLAN_DRAFT)
    solver_status: Mapped[str] = mapped_column(String(24), nullable=False)
    kerf_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    min_remnant_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    total_stock_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_count: Mapped[int] = mapped_column(Integer, nullable=False)
    pieces_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    kerf_loss_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    usable_remnant_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    scrap_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    lower_bound_mm: Mapped[int | None] = mapped_column(Integer)
    nodes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Snapshot wejścia algorytmu (długości, odcinki-kandydaci, limity) – do audytu i wyjaśnienia wyniku.
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = _now_col()
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship()
    bars: Mapped[list[PlanBar]] = relationship(
        back_populates="plan", order_by="PlanBar.position", cascade="all, delete-orphan"
    )
    execution: Mapped[PlanExecution | None] = relationship(back_populates="plan")


class PlanBar(Base):
    """Przydział fizycznego odcinka do planu wraz z bilansem cięcia."""

    __tablename__ = "plan_bars"
    __table_args__ = (
        UniqueConstraint("plan_id", "stock_item_id", name="uq_plan_bar_stock"),
        UniqueConstraint("plan_id", "position", name="uq_plan_bar_position"),
        CheckConstraint("kerf_loss_mm >= 0 AND remainder_mm >= 0", name="ck_plan_bar_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("cutting_plans.id", ondelete="CASCADE"), nullable=False
    )
    stock_item_id: Mapped[int] = mapped_column(ForeignKey("stock_items.id"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    stock_length_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    cut_count: Mapped[int] = mapped_column(Integer, nullable=False)
    kerf_loss_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    remainder_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    usable_remnant: Mapped[bool] = mapped_column(Boolean, nullable=False)

    plan: Mapped[CuttingPlan] = relationship(back_populates="bars")
    stock_item: Mapped[StockItem] = relationship()
    pieces: Mapped[list[PlanPiece]] = relationship(
        back_populates="bar", order_by="PlanPiece.position", cascade="all, delete-orphan"
    )


class PlanPiece(Base):
    """Element wycinany z odcinka. Długość i etykieta są kopią – plan pozostaje czytelny
    nawet po usunięciu pozycji zapotrzebowania (wtedy demand_item_id = NULL)."""

    __tablename__ = "plan_pieces"
    __table_args__ = (
        UniqueConstraint("plan_bar_id", "position", name="uq_plan_piece_position"),
        CheckConstraint("length_mm > 0", name="ck_plan_piece_length_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_bar_id: Mapped[int] = mapped_column(
        ForeignKey("plan_bars.id", ondelete="CASCADE"), nullable=False, index=True
    )
    demand_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("demand_items.id", ondelete="SET NULL"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    length_mm: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))

    bar: Mapped[PlanBar] = relationship(back_populates="pieces")


class PlanExecution(Base):
    """Zatwierdzenie wykonania planu. UNIQUE(plan_id) – plan można wykonać tylko raz."""

    __tablename__ = "plan_executions"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("cutting_plans.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    executed_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    executed_at: Mapped[datetime] = _now_col()

    plan: Mapped[CuttingPlan] = relationship(back_populates="execution")
    remnants: Mapped[list[StockItem]] = relationship(
        primaryjoin="PlanExecution.id == StockItem.source_execution_id",
        foreign_keys="StockItem.source_execution_id",
        viewonly=True,
        order_by="StockItem.id",
    )
