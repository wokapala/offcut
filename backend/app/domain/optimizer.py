"""Optymalizacja rozkroju jednowymiarowego (1D cutting stock z fizycznymi odcinkami).

Funkcja celu (porządek leksykograficzny):
  1. pokryć całe zapotrzebowanie,
  2. zminimalizować łączną długość zużytych odcinków wejściowych,
  3. przy remisie zminimalizować liczbę użytych odcinków.

Dwie metody dla tego samego wejścia:
  * ``greedy``  – first-fit decreasing: elementy od najdłuższego, każdy do pierwszego
    otwartego odcinka, w którym się mieści; gdy brak – otwiera najkrótszy wolny
    odcinek, w którym element się zmieści,
  * ``branch_and_bound`` – przeszukiwanie w głąb z odcinaniem gałęzi przez dolne
    ograniczenie, startujące od rozwiązania heurystyki, z limitem węzłów i czasu.

Problemy dla różnych specyfikacji materiału są niezależne, więc ``optimize``
rozwiązuje każdą grupę osobno i sumuje wyniki.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.domain.cutting import fits

# Statusy wyniku
HEURISTIC = "HEURISTIC"  # wynik heurystyki – bez gwarancji jakości
OPTIMAL = "OPTIMAL"  # przeszukiwanie zakończone – wynik optymalny dla funkcji celu
BEST_FOUND = "BEST_FOUND"  # limit osiągnięty – najlepszy znaleziony w limicie
INFEASIBLE = "INFEASIBLE"  # materiału na pewno nie wystarczy (lub heurystyka nie znalazła planu)
NO_SOLUTION_IN_LIMIT = "NO_SOLUTION_IN_LIMIT"  # limit osiągnięty bez żadnego planu

GREEDY = "GREEDY"
BRANCH_AND_BOUND = "BRANCH_AND_BOUND"


@dataclass(frozen=True)
class Stock:
    id: int
    length: int


@dataclass(frozen=True)
class Piece:
    demand_id: int
    length: int


@dataclass(frozen=True)
class Group:
    """Podproblem jednej specyfikacji materiału."""

    spec_id: int
    stocks: tuple[Stock, ...]
    pieces: tuple[Piece, ...]


@dataclass
class Bar:
    stock: Stock
    pieces: list[Piece] = field(default_factory=list)


@dataclass
class Limits:
    max_nodes: int = 300_000
    time_limit_s: float = 3.0


@dataclass
class Result:
    method: str
    status: str
    bars: list[Bar]
    unplaced: list[Piece]
    nodes: int = 0
    elapsed_ms: int = 0
    lower_bound: int = 0  # dolne ograniczenie łącznej długości zużytych odcinków
    parts: list[Result] = field(default_factory=list)  # wyniki poszczególnych specyfikacji
    spec_id: int | None = None

    @property
    def complete(self) -> bool:
        return not self.unplaced and self.status not in (INFEASIBLE, NO_SOLUTION_IN_LIMIT)

    @property
    def total_stock_length(self) -> int:
        return sum(b.stock.length for b in self.bars)

    @property
    def stock_count(self) -> int:
        return len(self.bars)


def cost(bars: list[Bar]) -> tuple[int, int]:
    return (sum(b.stock.length for b in bars), len(bars))


def _sorted_pieces(pieces) -> list[Piece]:
    return sorted(pieces, key=lambda p: (-p.length, p.demand_id))


def _sorted_stocks(stocks) -> list[Stock]:
    return sorted(stocks, key=lambda s: (s.length, s.id))


def _root_lower_bound(pieces: list[Piece], stocks: list[Stock]) -> int:
    """Każdy odcinek pomieści co najwyżej swoją długość elementów."""
    if not pieces:
        return 0
    return max(sum(p.length for p in pieces), min((s.length for s in stocks), default=0))


# ---------------------------------------------------------------------------
# Heurystyka bazowa
# ---------------------------------------------------------------------------


def greedy_group(group: Group, kerf: int) -> Result:
    start = time.perf_counter()
    free = _sorted_stocks(group.stocks)
    bars: list[Bar] = []
    unplaced: list[Piece] = []
    for piece in _sorted_pieces(group.pieces):
        for bar in bars:
            if fits(bar.stock.length, [p.length for p in bar.pieces] + [piece.length], kerf):
                bar.pieces.append(piece)
                break
        else:
            chosen = next((s for s in free if s.length >= piece.length), None)
            if chosen is None:
                unplaced.append(piece)
                continue
            free.remove(chosen)
            bars.append(Bar(chosen, [piece]))
    return Result(
        method=GREEDY,
        status=INFEASIBLE if unplaced else HEURISTIC,
        bars=bars,
        unplaced=unplaced,
        elapsed_ms=int((time.perf_counter() - start) * 1000),
        lower_bound=_root_lower_bound(list(group.pieces), list(group.stocks)),
    )


# ---------------------------------------------------------------------------
# Branch and bound
# ---------------------------------------------------------------------------


class _LimitReached(Exception):
    pass


def branch_and_bound_group(group: Group, kerf: int, limits: Limits,
                           incumbent: Result | None = None) -> Result:
    start = time.perf_counter()
    deadline = start + limits.time_limit_s
    pieces = _sorted_pieces(group.pieces)
    stocks = _sorted_stocks(group.stocks)
    n = len(pieces)
    root_lb = _root_lower_bound(pieces, stocks)

    # suffix[i] = suma długości elementów i..n-1
    suffix = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + pieces[i].length

    best_bars: list[tuple[int, list[int]]] | None = None  # (indeks odcinka, indeksy elementów)
    best_cost: tuple[int, int] = (10**18, 10**9)
    if incumbent is not None and incumbent.complete:
        best_cost = cost(incumbent.bars)

    # Szybki dowód braku materiału: za długi element albo za mało materiału łącznie.
    if n and (pieces[0].length > max((s.length for s in stocks), default=0)
              or suffix[0] > sum(s.length for s in stocks)):
        elapsed = int((time.perf_counter() - start) * 1000)
        return Result(BRANCH_AND_BOUND, INFEASIBLE, [], list(pieces), 0, elapsed, root_lb)

    # Stan przeszukiwania
    bar_stock: list[int] = []  # indeks odcinka w ``stocks`` dla każdego otwartego odcinka
    bar_n: list[int] = []  # liczba elementów
    bar_sum: list[int] = []  # suma długości elementów
    bar_items: list[list[int]] = []
    used = [False] * len(stocks)
    choice = [0] * n  # indeks odcinka (w kolejności otwarcia) wybrany dla elementu
    nodes = 0
    cur_cost = 0
    unused_total = sum(s.length for s in stocks)

    def lower_bound(i: int) -> tuple[int, int]:
        free = 0
        for b in range(len(bar_stock)):
            free += max(0, stocks[bar_stock[b]].length - bar_sum[b] - kerf * bar_n[b])
        deficit = suffix[i] - free
        if deficit <= 0:
            return (cur_cost, len(bar_stock))
        if deficit > unused_total:
            return (10**18, 10**9)  # pozostałego materiału na pewno nie wystarczy
        cheapest = min((s.length for k, s in enumerate(stocks) if not used[k]), default=None)
        if cheapest is None:
            return (10**18, 10**9)
        return (cur_cost + max(deficit, cheapest), len(bar_stock) + 1)

    def dfs(i: int) -> None:
        nonlocal nodes, best_cost, best_bars, cur_cost, unused_total
        nodes += 1
        if nodes > limits.max_nodes or (nodes & 1023) == 0 and time.perf_counter() > deadline:
            raise _LimitReached
        if i == n:
            c = (cur_cost, len(bar_stock))
            if c < best_cost:
                best_cost = c
                best_bars = [(bar_stock[b], list(bar_items[b])) for b in range(len(bar_stock))]
            return
        if lower_bound(i) >= best_cost:
            return

        p = pieces[i].length
        # Elementy o tej samej długości są wymienne: przydzielamy je w niedmalejącej
        # kolejności odcinków, co usuwa permutacje tego samego rozwiązania.
        min_bar = choice[i - 1] if i > 0 and pieces[i - 1].length == p else 0

        # 1) istniejące odcinki (pomijamy odcinki o identycznym stanie)
        tried_states: set[tuple[int, int, int]] = set()
        for b in range(min_bar, len(bar_stock)):
            length = stocks[bar_stock[b]].length
            if bar_sum[b] + p + kerf * bar_n[b] > length:
                continue
            state = (length, bar_n[b], bar_sum[b])
            if state in tried_states:
                continue
            tried_states.add(state)
            bar_n[b] += 1
            bar_sum[b] += p
            bar_items[b].append(i)
            choice[i] = b
            dfs(i + 1)
            bar_items[b].pop()
            bar_sum[b] -= p
            bar_n[b] -= 1

        # 2) nowy odcinek – po jednym z każdej długości (odcinki tej samej długości są wymienne)
        tried_lengths: set[int] = set()
        for k, s in enumerate(stocks):
            if used[k] or s.length < p or s.length in tried_lengths:
                continue
            tried_lengths.add(s.length)
            if (cur_cost + s.length, len(bar_stock) + 1) >= best_cost:
                break  # odcinki są posortowane rosnąco – dalsze są jeszcze droższe
            used[k] = True
            bar_stock.append(k)
            bar_n.append(1)
            bar_sum.append(p)
            bar_items.append([i])
            cur_cost += s.length
            unused_total -= s.length
            choice[i] = len(bar_stock) - 1
            dfs(i + 1)
            cur_cost -= s.length
            unused_total += s.length
            bar_items.pop()
            bar_sum.pop()
            bar_n.pop()
            bar_stock.pop()
            used[k] = False

    finished = True
    try:
        dfs(0)
    except _LimitReached:
        finished = False
    elapsed = int((time.perf_counter() - start) * 1000)

    if best_bars is not None:
        bars = [Bar(stocks[k], [pieces[j] for j in items]) for k, items in best_bars]
    elif incumbent is not None and incumbent.complete:
        bars = [Bar(b.stock, list(b.pieces)) for b in incumbent.bars]  # B&B nie poprawił heurystyki
    else:
        bars = []

    if bars:
        status = OPTIMAL if finished else BEST_FOUND
        unplaced: list[Piece] = []
    else:
        status = INFEASIBLE if finished else NO_SOLUTION_IN_LIMIT
        unplaced = list(pieces)
    for bar in bars:
        bar.pieces.sort(key=lambda p: (-p.length, p.demand_id))
    bars.sort(key=lambda b: (b.stock.length, b.stock.id))
    return Result(BRANCH_AND_BOUND, status, bars, unplaced, nodes, elapsed, root_lb)


# ---------------------------------------------------------------------------
# Wiele specyfikacji
# ---------------------------------------------------------------------------


def _merge(method: str, parts: list[Result]) -> Result:
    bars = [b for r in parts for b in r.bars]
    unplaced = [p for r in parts for p in r.unplaced]
    statuses = {r.status for r in parts}
    default = OPTIMAL if method == BRANCH_AND_BOUND else HEURISTIC
    status = next((s for s in (INFEASIBLE, NO_SOLUTION_IN_LIMIT, BEST_FOUND, HEURISTIC, OPTIMAL)
                   if s in statuses), default)
    return Result(
        method=method,
        status=status,
        bars=bars,
        unplaced=unplaced,
        parts=parts,
        nodes=sum(r.nodes for r in parts),
        elapsed_ms=sum(r.elapsed_ms for r in parts),
        lower_bound=sum(r.lower_bound for r in parts),
    )


def optimize(groups: list[Group], kerf: int, limits: Limits | None = None) -> tuple[Result, Result]:
    """Uruchamia obie metody dla tego samego wejścia. Zwraca (heurystyka, branch and bound)."""
    if kerf < 0:
        raise ValueError("Rzaz nie może być ujemny")
    limits = limits or Limits()
    greedy_parts, bnb_parts = [], []
    for g in groups:
        gr = greedy_group(g, kerf)
        bb = branch_and_bound_group(g, kerf, limits, incumbent=gr)
        gr.spec_id = bb.spec_id = g.spec_id
        greedy_parts.append(gr)
        bnb_parts.append(bb)
    return _merge(GREEDY, greedy_parts), _merge(BRANCH_AND_BOUND, bnb_parts)
