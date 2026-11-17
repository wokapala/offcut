"""Ograniczenia bazy danych – ostatnia linia obrony niezależna od kodu Pythona."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def base(db):
    db.execute(text("""
        INSERT INTO users (id, email, full_name, password_hash) VALUES (1, 'u@x.pl', 'U', 'x');
        INSERT INTO workshops (id, name) VALUES (1, 'A'), (2, 'B');
        INSERT INTO material_specs (id, workshop_id, material, section) VALUES (1, 1, 'Sosna', '40x20'),
                                                                             (2, 2, 'Dąb', '20x20');
        INSERT INTO projects (id, workshop_id, name, kerf_mm, min_remnant_mm, revision, created_by_id)
            VALUES (1, 1, 'P', 3, 300, 1, 1);
        INSERT INTO stock_items (id, workshop_id, material_spec_id, length_mm, status, is_remnant)
            VALUES (1, 1, 1, 3000, 'AVAILABLE', false);
    """))
    db.commit()
    return db


def _plan_sql(plan_id, status):
    return text(f"""
        INSERT INTO cutting_plans (id, project_id, project_revision, method, status, solver_status, kerf_mm,
            min_remnant_mm, total_stock_mm, stock_count, pieces_mm, kerf_loss_mm, usable_remnant_mm, scrap_mm,
            nodes, elapsed_ms, input_snapshot, created_by_id)
        VALUES ({plan_id}, 1, 1, 'GREEDY', '{status}', 'HEURISTIC', 3, 300, 3000, 1, 2000, 3, 997, 0,
            0, 0, '{{}}', 1)
    """)


@pytest.mark.parametrize("sql", [
    "INSERT INTO stock_items (workshop_id, material_spec_id, length_mm, status, is_remnant) VALUES (1, 1, 0, 'AVAILABLE', false)",
    "INSERT INTO stock_items (workshop_id, material_spec_id, length_mm, status, is_remnant) VALUES (1, 1, 100, 'RESERVED', false)",
    "INSERT INTO stock_items (workshop_id, material_spec_id, length_mm, status, is_remnant) VALUES (1, 1, 100, 'LOST', false)",
    # specyfikacja z innego warsztatu niż odcinek
    "INSERT INTO stock_items (workshop_id, material_spec_id, length_mm, status, is_remnant) VALUES (1, 2, 100, 'AVAILABLE', false)",
    "INSERT INTO demand_items (project_id, material_spec_id, length_mm, quantity) VALUES (1, 1, 100, 0)",
    "INSERT INTO projects (workshop_id, name, kerf_mm, min_remnant_mm, revision, created_by_id) VALUES (1, 'X', -1, 0, 1, 1)",
    "INSERT INTO material_specs (workshop_id, material, section) VALUES (1, 'Sosna', '40x20')",
])
def test_invalid_rows_rejected(base, sql):
    with pytest.raises(IntegrityError):
        base.execute(text(sql))
        base.flush()
    base.rollback()


def test_plan_balance_check(base):
    with pytest.raises(IntegrityError):
        base.execute(text(_plan_sql(1, "DRAFT").text.replace("997", "500")))
    base.rollback()


def test_one_active_plan_per_project(base):
    base.execute(_plan_sql(1, "RESERVED"))
    base.execute(_plan_sql(2, "DRAFT"))
    base.commit()
    with pytest.raises(IntegrityError):
        base.execute(_plan_sql(3, "EXECUTED"))
    base.rollback()


def test_plan_executed_only_once(base):
    base.execute(_plan_sql(1, "EXECUTED"))
    base.execute(text("INSERT INTO plan_executions (plan_id, executed_by_id) VALUES (1, 1)"))
    base.commit()
    with pytest.raises(IntegrityError):
        base.execute(text("INSERT INTO plan_executions (plan_id, executed_by_id) VALUES (1, 1)"))
    base.rollback()


def test_same_stock_twice_in_plan_rejected(base):
    base.execute(_plan_sql(1, "DRAFT"))
    row = "(1, 1, {pos}, 3000, 1, 3, 997, true)"
    with pytest.raises(IntegrityError):
        base.execute(text(
            "INSERT INTO plan_bars (plan_id, stock_item_id, position, stock_length_mm, cut_count, kerf_loss_mm, "
            f"remainder_mm, usable_remnant) VALUES {row.format(pos=0)}, {row.format(pos=1)}"
        ))
    base.rollback()
