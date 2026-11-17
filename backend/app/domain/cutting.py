"""Model fizyczny cięcia jednego odcinka (rzaz) i walidator planu.

Wszystkie długości są liczbami całkowitymi w milimetrach.

Model rzazu (szczegóły i przykłady: docs/ALGORITHM.md):
  * elementy odcinamy kolejno od początku odcinka,
  * między dwoma sąsiednimi elementami jest jedno cięcie o szerokości ``kerf``,
  * jeśli po ostatnim elemencie zostaje materiał, potrzebne jest jeszcze jedno
    cięcie oddzielające ostatni element od pozostałości; zjada ono
    ``min(kerf, pozostały materiał)``,
  * jeśli ostatni element kończy się dokładnie na końcu odcinka, tego cięcia nie ma.

Bilans każdego odcinka:  długość = suma elementów + rzaz łącznie + pozostałość.
Pozostałość >= ``min_remnant`` jest użyteczną resztką (wraca do magazynu),
mniejsza jest odpadem.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


class PlanValidationError(ValueError):
    """Plan jest niezgodny z regułami domeny. ``problems`` zawiera listę opisów."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class BarBalance:
    """Bilans długości jednego fizycznego odcinka po cięciu."""

    stock_length: int
    pieces_length: int
    piece_count: int
    cut_count: int
    kerf_loss: int
    remainder: int
    usable_remnant: bool

    @property
    def waste(self) -> int:
        """Materiał bezpowrotnie stracony: rzaz + nieużyteczna pozostałość."""
        return self.kerf_loss + (0 if self.usable_remnant else self.remainder)


def occupied_length(piece_lengths: list[int] | tuple[int, ...], kerf: int) -> int:
    """Długość zajęta przez elementy i cięcia *między* nimi (bez cięcia końcowego)."""
    if not piece_lengths:
        return 0
    return sum(piece_lengths) + kerf * (len(piece_lengths) - 1)


def fits(stock_length: int, piece_lengths: list[int] | tuple[int, ...], kerf: int) -> bool:
    return occupied_length(piece_lengths, kerf) <= stock_length


def bar_balance(stock_length: int, piece_lengths: list[int] | tuple[int, ...], kerf: int,
                min_remnant: int) -> BarBalance:
    """Liczy bilans odcinka. Rzuca PlanValidationError, gdy elementy się nie mieszczą."""
    if stock_length <= 0:
        raise PlanValidationError(["Długość odcinka musi być dodatnia"])
    if kerf < 0:
        raise PlanValidationError(["Rzaz nie może być ujemny"])
    if min_remnant < 0:
        raise PlanValidationError(["Próg użytecznej resztki nie może być ujemny"])
    if not piece_lengths:
        raise PlanValidationError(["Odcinek w planie musi mieć co najmniej jeden element"])
    if any(p <= 0 for p in piece_lengths):
        raise PlanValidationError(["Długości elementów muszą być dodatnie"])

    n = len(piece_lengths)
    occupied = occupied_length(piece_lengths, kerf)
    if occupied > stock_length:
        raise PlanValidationError([
            f"Elementy {list(piece_lengths)} z rzazem {kerf} mm zajmują {occupied} mm, "
            f"a odcinek ma {stock_length} mm"
        ])

    rest = stock_length - occupied
    final_cut = min(kerf, rest)  # 0 gdy ostatni element kończy się równo z końcem odcinka
    remainder = rest - final_cut
    kerf_loss = kerf * (n - 1) + final_cut
    cut_count = (n - 1) + (1 if rest > 0 else 0)
    usable = remainder > 0 and remainder >= min_remnant

    balance = BarBalance(
        stock_length=stock_length,
        pieces_length=sum(piece_lengths),
        piece_count=n,
        cut_count=cut_count,
        kerf_loss=kerf_loss,
        remainder=remainder,
        usable_remnant=usable,
    )
    assert balance.pieces_length + balance.kerf_loss + balance.remainder == stock_length
    return balance


# ---------------------------------------------------------------------------
# Walidator całego planu – wspólny dla planów ręcznych i wyników algorytmów.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StockInfo:
    id: int
    spec_id: int
    length: int


@dataclass(frozen=True)
class DemandInfo:
    id: int
    spec_id: int
    length: int
    quantity: int


@dataclass(frozen=True)
class BarAssignment:
    """Jeden odcinek w planie: id odcinka magazynowego i kolejne elementy (id pozycji zapotrzebowania)."""

    stock_id: int
    demand_ids: tuple[int, ...]


@dataclass(frozen=True)
class PlanSummary:
    bars: tuple[tuple[BarAssignment, BarBalance], ...]
    total_stock_length: int
    stock_count: int
    pieces_length: int
    kerf_loss: int
    usable_remnant_length: int
    scrap_length: int  # nieużyteczne pozostałości

    @property
    def waste(self) -> int:
        return self.kerf_loss + self.scrap_length


def validate_plan(
    bars: list[BarAssignment],
    stock: dict[int, StockInfo],
    demand: dict[int, DemandInfo],
    kerf: int,
    min_remnant: int,
) -> PlanSummary:
    """Sprawdza kompletny plan i zwraca jego bilans.

    ``stock`` – odcinki, których plan *może* użyć (np. dostępne w magazynie).
    ``demand`` – pozycje zapotrzebowania projektu.
    Reguły: każdy odcinek co najwyżej raz, zgodność materiału i przekroju,
    elementy mieszczą się z rzazem, zapotrzebowanie pokryte dokładnie.
    """
    problems: list[str] = []
    if kerf < 0:
        problems.append("Rzaz nie może być ujemny")
    if min_remnant < 0:
        problems.append("Próg użytecznej resztki nie może być ujemny")
    for d in demand.values():
        if d.length <= 0 or d.quantity <= 0:
            problems.append(f"Pozycja {d.id}: długość i liczba sztuk muszą być dodatnie")
    if problems:
        raise PlanValidationError(problems)

    seen_stock: set[int] = set()
    produced: Counter[int] = Counter()
    checked: list[tuple[BarAssignment, BarBalance]] = []

    for bar in bars:
        s = stock.get(bar.stock_id)
        if s is None:
            problems.append(f"Odcinek {bar.stock_id} nie jest dostępny dla tego planu")
            continue
        if bar.stock_id in seen_stock:
            problems.append(f"Odcinek {bar.stock_id} użyty w planie więcej niż raz")
            continue
        seen_stock.add(bar.stock_id)

        lengths: list[int] = []
        for did in bar.demand_ids:
            d = demand.get(did)
            if d is None:
                problems.append(f"Element odwołuje się do nieznanej pozycji zapotrzebowania {did}")
                continue
            if d.spec_id != s.spec_id:
                problems.append(
                    f"Pozycja {did} wymaga innego materiału/przekroju niż odcinek {s.id}"
                )
                continue
            lengths.append(d.length)
            produced[did] += 1
        try:
            checked.append((bar, bar_balance(s.length, lengths, kerf, min_remnant)))
        except PlanValidationError as exc:
            problems.extend(f"Odcinek {s.id}: {p}" for p in exc.problems)

    for d in demand.values():
        if produced[d.id] != d.quantity:
            problems.append(
                f"Pozycja {d.id} ({d.length} mm): w planie {produced[d.id]} szt., wymagane {d.quantity}"
            )

    if problems:
        raise PlanValidationError(problems)

    balances = [b for _, b in checked]
    return PlanSummary(
        bars=tuple(checked),
        total_stock_length=sum(b.stock_length for b in balances),
        stock_count=len(balances),
        pieces_length=sum(b.pieces_length for b in balances),
        kerf_loss=sum(b.kerf_loss for b in balances),
        usable_remnant_length=sum(b.remainder for b in balances if b.usable_remnant),
        scrap_length=sum(b.remainder for b in balances if not b.usable_remnant),
    )
