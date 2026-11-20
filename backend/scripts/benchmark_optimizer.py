"""Pomiar z docs/ALGORITHM.md §6: FFD vs branch and bound na losowych instancjach.

Uruchomienie (z katalogu backend):  uv run python -m scripts.benchmark_optimizer
Instancje są deterministyczne (ziarno 5); czasy zależą od komputera, a przy limicie czasu
także wynik B&B na wolniejszej maszynie może być inny.
"""

import random
import time

from app.domain.optimizer import Group, Piece, Stock, cost, optimize


def main() -> None:
    rnd = random.Random(5)
    print("elementów | FFD [mm/odc.] | B&B [mm/odc.] | status B&B | węzły | czas")
    for n in (10, 20, 40, 80, 200):
        stocks = tuple(Stock(i, rnd.choice([3000, 3000, 3000, 1200, 1800, 2400, 900])) for i in range(min(n, 120)))
        pieces = tuple(Piece(length, length) for length in
                       (rnd.choice([350, 420, 560, 600, 640, 720, 800, 950, 1100]) for _ in range(n)))
        start = time.perf_counter()
        greedy, bnb = optimize([Group(1, stocks, pieces)], kerf=3)
        elapsed = time.perf_counter() - start
        print(f"{n:9} | {cost(greedy.bars)} | {cost(bnb.bars)} | {bnb.status} | {bnb.nodes} | {elapsed:.2f} s")


if __name__ == "__main__":
    main()
