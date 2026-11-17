"""Model rzazu i walidator planu – testy bez bazy danych i HTTP."""

import pytest

from app.domain.cutting import (
    BarAssignment,
    DemandInfo,
    PlanValidationError,
    StockInfo,
    bar_balance,
    validate_plan,
)


def test_cuts_between_pieces_and_cut_before_remnant():
    # 3000 = 1000 + 3 + 1000 + 3 (cięcie oddzielające resztkę) + 994
    b = bar_balance(3000, [1000, 1000], kerf=3, min_remnant=300)
    assert b.cut_count == 2
    assert b.kerf_loss == 6
    assert b.remainder == 994
    assert b.usable_remnant
    assert b.pieces_length + b.kerf_loss + b.remainder == 3000


def test_exact_fit_has_no_final_cut():
    # 2003 = 1000 + 3 + 1000 – ostatni element kończy się na końcu odcinka
    b = bar_balance(2003, [1000, 1000], kerf=3, min_remnant=300)
    assert b.cut_count == 1
    assert b.kerf_loss == 3
    assert b.remainder == 0
    assert not b.usable_remnant
    assert b.waste == 3


def test_single_piece_exact_length_needs_no_cut():
    b = bar_balance(1200, [1200], kerf=3, min_remnant=300)
    assert (b.cut_count, b.kerf_loss, b.remainder) == (0, 0, 0)


def test_remainder_thinner_than_kerf_is_consumed_by_last_cut():
    # po elementach zostają 2 mm < rzaz 3 mm – ostatnie cięcie zjada je w całości
    b = bar_balance(1005, [500, 500], kerf=3, min_remnant=300)
    assert b.kerf_loss == 3 + 2
    assert b.remainder == 0
    assert b.pieces_length + b.kerf_loss + b.remainder == 1005


def test_pieces_not_fitting_with_kerf_are_rejected():
    # 1000 + 3 + 1000 = 2003 > 2002
    with pytest.raises(PlanValidationError):
        bar_balance(2002, [1000, 1000], kerf=3, min_remnant=300)


def test_short_remainder_is_scrap_not_remnant():
    b = bar_balance(1000, [700], kerf=3, min_remnant=300)
    assert b.remainder == 297
    assert not b.usable_remnant
    assert b.waste == 3 + 297
    b2 = bar_balance(1003, [700], kerf=3, min_remnant=300)
    assert b2.remainder == 300 and b2.usable_remnant and b2.waste == 3


def test_zero_kerf_is_allowed_negative_is_not():
    b = bar_balance(1000, [500, 500], kerf=0, min_remnant=0)
    assert b.remainder == 0 and b.kerf_loss == 0
    with pytest.raises(PlanValidationError):
        bar_balance(1000, [500], kerf=-1, min_remnant=0)


@pytest.mark.parametrize("pieces", [[0], [-5], []])
def test_non_positive_or_empty_pieces_rejected(pieces):
    with pytest.raises(PlanValidationError):
        bar_balance(1000, pieces, kerf=3, min_remnant=300)


# --- validate_plan -----------------------------------------------------------

STOCK = {
    1: StockInfo(1, spec_id=10, length=3000),
    2: StockInfo(2, spec_id=10, length=1200),
    3: StockInfo(3, spec_id=20, length=3000),  # inny materiał / przekrój
}
DEMAND = {
    100: DemandInfo(100, spec_id=10, length=1000, quantity=2),
    101: DemandInfo(101, spec_id=10, length=500, quantity=1),
}


def test_valid_plan_summary_balances():
    s = validate_plan(
        [BarAssignment(1, (100, 100, 101))], STOCK, DEMAND, kerf=3, min_remnant=300
    )
    assert s.stock_count == 1
    assert s.total_stock_length == 3000
    assert s.pieces_length == 2500
    assert s.kerf_loss == 9
    assert s.usable_remnant_length == 491
    assert s.total_stock_length == s.pieces_length + s.kerf_loss + s.usable_remnant_length + s.scrap_length


def test_incompatible_material_is_rejected():
    with pytest.raises(PlanValidationError) as e:
        validate_plan([BarAssignment(3, (100, 100, 101))], STOCK, DEMAND, 3, 300)
    assert any("innego materiału" in p for p in e.value.problems)


def test_incomplete_coverage_is_rejected():
    with pytest.raises(PlanValidationError) as e:
        validate_plan([BarAssignment(1, (100, 101))], STOCK, DEMAND, 3, 300)
    assert any("wymagane 2" in p for p in e.value.problems)


def test_overproduction_is_rejected():
    with pytest.raises(PlanValidationError):
        validate_plan([BarAssignment(1, (100, 100, 101)), BarAssignment(2, (101,))], STOCK, DEMAND, 3, 300)


def test_same_stock_twice_is_rejected():
    with pytest.raises(PlanValidationError) as e:
        validate_plan([BarAssignment(1, (100, 100)), BarAssignment(1, (101,))], STOCK, DEMAND, 3, 300)
    assert any("więcej niż raz" in p for p in e.value.problems)


def test_unknown_stock_is_rejected():
    with pytest.raises(PlanValidationError):
        validate_plan([BarAssignment(99, (100, 100, 101))], STOCK, DEMAND, 3, 300)


def test_overfull_bar_is_rejected():
    with pytest.raises(PlanValidationError):
        validate_plan([BarAssignment(2, (100, 101)), BarAssignment(1, (100,))], STOCK, DEMAND, 3, 300)
