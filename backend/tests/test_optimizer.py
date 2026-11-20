"""Optymalizator: poprawność planów obu metod, porównanie z pełnym przeglądem, limity."""

import itertools
import random

import pytest

from app.domain.cutting import BarAssignment, DemandInfo, StockInfo, fits, validate_plan
from app.domain.optimizer import (
    BEST_FOUND,
    HEURISTIC,
    INFEASIBLE,
    NO_SOLUTION_IN_LIMIT,
    OPTIMAL,
    Group,
    Limits,
    Piece,
    Stock,
    cost,
    optimize,
)


def brute_force(group: Group, kerf: int):
    """Pełny przegląd przydziałów element -> odcinek. Zwraca (łączna długość, liczba) lub None."""
    stocks, pieces = list(group.stocks), list(group.pieces)
    best = None
    for assign in itertools.product(range(len(stocks)), repeat=len(pieces)):
        bins: dict[int, list[int]] = {}
        for pi, si in enumerate(assign):
            bins.setdefault(si, []).append(pieces[pi].length)
        if all(fits(stocks[si].length, lengths, kerf) for si, lengths in bins.items()):
            c = (sum(stocks[si].length for si in bins), len(bins))
            best = c if best is None or c < best else best
    return best


def assert_valid(result, group: Group, kerf: int, min_remnant: int = 300):
    """Wynik algorytmu przechodzi przez ten sam walidator co plany ręczne."""
    stock = {s.id: StockInfo(s.id, group.spec_id, s.length) for s in group.stocks}
    counts: dict[int, int] = {}
    lengths: dict[int, int] = {}
    for p in group.pieces:
        counts[p.demand_id] = counts.get(p.demand_id, 0) + 1
        lengths[p.demand_id] = p.length
    demand = {d: DemandInfo(d, group.spec_id, lengths[d], q) for d, q in counts.items()}
    bars = [BarAssignment(b.stock.id, tuple(p.demand_id for p in b.pieces)) for b in result.bars]
    summary = validate_plan(bars, stock, demand, kerf, min_remnant)
    assert summary.total_stock_length == result.total_stock_length
    return summary


def pieces(*spec):
    """pieces((demand_id, length, qty), ...)"""
    return tuple(Piece(d, l) for d, l, q in spec for _ in range(q))


DEMO_GROUP = Group(
    spec_id=1,
    stocks=(Stock(1, 1250), Stock(2, 1900), Stock(3, 1400), Stock(4, 900),
            Stock(10, 3000), Stock(11, 3000), Stock(12, 3000)),
    pieces=pieces((1, 560, 3), (2, 950, 2), (3, 600, 1)),
)


def test_demo_case_branch_and_bound_beats_greedy():
    greedy, bnb = optimize([DEMO_GROUP], kerf=3)
    assert greedy.status == HEURISTIC and bnb.status == OPTIMAL
    g, b = assert_valid(greedy, DEMO_GROUP, 3), assert_valid(bnb, DEMO_GROUP, 3)
    assert cost(greedy.bars) == (5450, 4)
    assert cost(bnb.bars) == (4900, 2)
    assert b.waste < g.waste
    assert cost(bnb.bars) == brute_force(DEMO_GROUP, 3)


def test_exact_fit_uses_whole_bar_without_final_cut():
    group = Group(1, (Stock(1, 2003),), pieces((1, 1000, 2)))
    greedy, bnb = optimize([group], kerf=3)
    for r in (greedy, bnb):
        s = assert_valid(r, group, 3)
        assert s.scrap_length == 0 and s.usable_remnant_length == 0 and s.kerf_loss == 3


def test_usable_remnant_reported():
    group = Group(1, (Stock(1, 3000),), pieces((1, 1000, 1)))
    _, bnb = optimize([group], kerf=3)
    s = assert_valid(bnb, group, 3, min_remnant=300)
    assert s.usable_remnant_length == 1997 and s.scrap_length == 0


def test_both_methods_equal_is_reported_honestly():
    group = Group(1, (Stock(1, 3000), Stock(2, 3000)), pieces((1, 700, 4)))
    greedy, bnb = optimize([group], kerf=3)
    assert cost(greedy.bars) == cost(bnb.bars) == (3000, 1)
    assert bnb.status == OPTIMAL


def test_not_enough_material():
    group = Group(1, (Stock(1, 1000), Stock(2, 1000)), pieces((1, 900, 3)))
    greedy, bnb = optimize([group], kerf=3)
    assert greedy.status == INFEASIBLE and len(greedy.unplaced) == 1
    assert bnb.status == INFEASIBLE and not bnb.complete


def test_piece_longer_than_any_stock():
    group = Group(1, (Stock(1, 3000),), pieces((1, 3500, 1)))
    _, bnb = optimize([group], kerf=3)
    assert bnb.status == INFEASIBLE


def test_kerf_makes_problem_infeasible():
    # bez rzazu 2 x 1000 mieści się w 2000, z rzazem 3 mm już nie
    group = Group(1, (Stock(1, 2000),), pieces((1, 1000, 2)))
    assert optimize([group], kerf=0)[1].status == OPTIMAL
    assert optimize([group], kerf=3)[1].status == INFEASIBLE


def test_branch_and_bound_finds_plan_when_greedy_fails():
    # FFD: 600 -> 900, 450 -> 1000, 450 -> 1000, 350 nie mieści się nigdzie.
    # Istnieje plan: 1000 = 600 + 350, 900 = 450 + 450.
    group = Group(1, (Stock(1, 1000), Stock(2, 900)), pieces((1, 600, 1), (2, 450, 2), (3, 350, 1)))
    greedy, bnb = optimize([group], kerf=0)
    assert not greedy.complete
    assert bnb.status == OPTIMAL
    assert_valid(bnb, group, 0)


def test_groups_are_solved_independently_per_material():
    pine = Group(1, (Stock(1, 3000),), pieces((1, 1000, 2)))
    alu = Group(2, (Stock(2, 2000),), pieces((2, 900, 2)))
    _, bnb = optimize([pine, alu], kerf=3)
    assert bnb.status == OPTIMAL
    by_stock = {b.stock.id: {p.demand_id for p in b.pieces} for b in bnb.bars}
    assert by_stock == {1: {1}, 2: {2}}


def test_limit_reached_returns_best_found_not_optimal():
    rnd = random.Random(3)
    stocks = tuple(Stock(i, rnd.choice([2400, 2700, 3000, 3300])) for i in range(40))
    ps = tuple(Piece(length, length) for length in (rnd.randint(30, 130) * 10 for _ in range(45)))
    group = Group(1, stocks, ps)
    greedy, bnb = optimize([group], kerf=3, limits=Limits(max_nodes=50, time_limit_s=5))
    assert bnb.status == BEST_FOUND
    assert bnb.complete
    assert cost(bnb.bars) <= cost(greedy.bars)
    assert_valid(bnb, group, 3)


def test_limit_without_any_solution():
    # heurystyka zawodzi, a limit 1 węzła nie pozwala znaleźć planu
    group = Group(1, (Stock(1, 1000), Stock(2, 900)), pieces((1, 600, 1), (2, 450, 2), (3, 350, 1)))
    _, bnb = optimize([group], kerf=0, limits=Limits(max_nodes=1))
    assert bnb.status == NO_SOLUTION_IN_LIMIT and not bnb.complete


def test_negative_kerf_rejected():
    with pytest.raises(ValueError):
        optimize([DEMO_GROUP], kerf=-1)


@pytest.mark.parametrize("seed", range(6))
def test_branch_and_bound_matches_exhaustive_search(seed):
    rnd = random.Random(seed)
    for _ in range(60):
        stocks = tuple(Stock(i + 1, rnd.choice([500, 800, 1000, 1200, 1500, 2000, 3000]))
                       for i in range(rnd.randint(1, 4)))
        ps = tuple(Piece(length, length)  # demand_id = długość, aby pozycja miała jedną długość
                   for length in (rnd.choice([150, 300, 450, 600, 700, 900, 1100])
                                  for _ in range(rnd.randint(1, 6))))
        kerf = rnd.choice([0, 3, 5])
        group = Group(1, stocks, ps)
        greedy, bnb = optimize([group], kerf)
        expected = brute_force(group, kerf)
        if expected is None:
            assert bnb.status == INFEASIBLE
            continue
        assert bnb.status == OPTIMAL
        assert cost(bnb.bars) == expected
        assert_valid(bnb, group, kerf)
        if greedy.complete:
            assert_valid(greedy, group, kerf)
            assert cost(greedy.bars) >= expected


def test_larger_demo_case_branch_and_bound_saves_bars():
    """Projekt demo „Stojak na drewno kominkowe” (13 elementów)."""
    group = Group(
        spec_id=1,
        stocks=tuple([Stock(i + 1, l) for i, l in enumerate([2100, 1300, 1100, 850, 700])]
                     + [Stock(20 + i, 2700) for i in range(5)]),
        pieces=pieces((1, 1150, 4), (2, 760, 4), (3, 520, 3), (4, 420, 2)),
    )
    greedy, bnb = optimize([group], kerf=3)
    g, b = assert_valid(greedy, group, 3), assert_valid(bnb, group, 3)
    assert cost(greedy.bars) == (14150, 8) and g.waste == 734
    assert bnb.status == OPTIMAL
    assert cost(bnb.bars) == (10200, 4) and b.waste == 160


def test_time_limit_is_shared_by_all_material_groups():
    import time

    def heavy(spec_id, seed):
        rnd = random.Random(seed)
        stocks = tuple(Stock(spec_id * 1000 + i, rnd.choice([2400, 2700, 3000, 3300])) for i in range(40))
        ps = tuple(Piece(spec_id * 1000 + length, length)
                   for length in (rnd.randint(30, 130) * 10 for _ in range(45)))
        return Group(spec_id, stocks, ps)

    groups = [heavy(s, s) for s in range(1, 5)]
    start = time.perf_counter()
    _, bnb = optimize(groups, kerf=3, limits=Limits(max_nodes=10**9, time_limit_s=0.5))
    elapsed = time.perf_counter() - start
    assert elapsed < 1.5  # 4 grupy, ale jeden wspólny limit 0,5 s (z zapasem na sprawdzanie co 1024 węzły)
    assert bnb.status == BEST_FOUND and bnb.complete
