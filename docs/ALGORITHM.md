# Algorytm rozkroju 1D

Kod: `backend/app/domain/cutting.py` (model rzazu, walidator) i `backend/app/domain/optimizer.py`
(heurystyka i branch and bound). Oba moduły są czystym Pythonem – testowane bez HTTP i bazy.

## 1. Dane wejściowe

Dla jednego projektu:

| Wejście | Opis |
|---|---|
| zapotrzebowanie | pozycje: specyfikacja (materiał + przekrój), długość [mm], liczba sztuk |
| odcinki-kandydaci | **fizyczne** odcinki magazynu w stanie `AVAILABLE`, o tej samej specyfikacji co pozycja; każdy ma własne ID (dwa odcinki 3000 mm to dwa różne zasoby) |
| rzaz `k` | szerokość materiału usuwanego przez jedno cięcie [mm], `k ≥ 0` |
| próg resztki `m` | minimalna długość pozostałości, która wraca do magazynu [mm] |

Wszystkie długości są liczbami całkowitymi w milimetrach – brak błędów zaokrągleń.

Zapotrzebowanie różnych specyfikacji to niezależne podproblemy (sosna nie może pochodzić z odcinka
aluminium), więc optymalizator rozwiązuje każdą grupę osobno i sumuje wyniki.

## 2. Model rzazu

Elementy odcinamy kolejno od początku odcinka o długości `L`:

* między dwoma sąsiednimi elementami jest **jedno cięcie** o szerokości `k`,
* jeżeli po ostatnim elemencie zostaje materiał, potrzebne jest **cięcie oddzielające resztkę** –
  zabiera ono `min(k, pozostały materiał)`,
* jeżeli ostatni element kończy się **dokładnie na końcu odcinka**, tego cięcia nie ma.

Dla elementów `p1..pn`:

```
zajęte    = p1 + … + pn + k·(n − 1)          warunek zmieszczenia: zajęte ≤ L
reszta    = L − zajęte
cięcie_końcowe = min(k, reszta)              (0, gdy reszta = 0)
rzaz      = k·(n − 1) + cięcie_końcowe
pozostałość = reszta − cięcie_końcowe
bilans:   L = suma elementów + rzaz + pozostałość
```

Pozostałość `≥ m` (i > 0) to **użyteczna resztka** – po wykonaniu planu trafia do magazynu jako nowy
odcinek z pochodzeniem (odcinek-rodzic, wykonanie planu). Pozostałość `< m` to **odpad**.
**Odpad planu = rzaz + nieużyteczne pozostałości.**

Przykłady (rzaz 3 mm, próg 300 mm) – wszystkie są testami w `tests/test_cutting.py`:

| Odcinek | Elementy | Cięcia | Rzaz | Pozostałość | Komentarz |
|---|---|---|---|---|---|
| 3000 | 1000, 1000 | 2 | 6 | 994 – resztka | `1000 + 3 + 1000 + 3 + 994` – drugie cięcie oddziela resztkę |
| 2003 | 1000, 1000 | 1 | 3 | 0 | dokładne wykorzystanie końca – brak cięcia końcowego |
| 1200 | 1200 | 0 | 0 | 0 | element równy odcinkowi |
| 1005 | 500, 500 | 2 | 5 | 0 | zostały 2 mm < rzaz – ostatnie cięcie zjada je w całości |
| 2002 | 1000, 1000 | – | – | – | **nie mieści się**: 1000 + 3 + 1000 = 2003 > 2002 |
| 1000 | 700 | 1 | 3 | 297 – odpad | poniżej progu 300 mm |

Wzór „liczba elementów − 1” liczy tylko cięcia *między* elementami; cięcie oddzielające resztkę jest
liczone osobno – dlatego bilans każdego odcinka zawsze się zgadza.

Ten sam model (`bar_balance`) i ten sam walidator (`validate_plan`) są używane dla planów ręcznych,
wyników heurystyki i wyników branch and bound. Z tych samych liczb powstają statystyki planu,
schemat w UI i resztki zapisywane do magazynu. Baza dodatkowo pilnuje bilansu planu ograniczeniem
`CHECK (total_stock_mm = pieces_mm + kerf_loss_mm + usable_remnant_mm + scrap_mm)`.

Walidator sprawdza: każdy odcinek użyty najwyżej raz, odcinek jest dostępny, zgodność materiału
i przekroju, zmieszczenie elementów z rzazem, pokrycie zapotrzebowania **dokładnie** (ani mniej, ani więcej).

## 3. Funkcja celu

Porównanie leksykograficzne:

1. pokryć **całe** zapotrzebowanie (plan niepełny nie może zostać zarezerwowany),
2. **zminimalizować łączną długość zużytych odcinków wejściowych**,
3. przy remisie – zminimalizować liczbę użytych odcinków.

Wpływ na resztki: ponieważ `suma zużytych odcinków = suma elementów + rzaz + wszystkie pozostałości`,
a suma elementów jest stała, minimalizujemy rzaz i pozostałości łącznie. Algorytm preferuje więc
krótsze odcinki (np. stare resztki), jeżeli pozwalają ciąć bez rozpoczynania długiej sztangi,
a nietknięte odcinki zostają w magazynie w całości.

**Ograniczenie:** funkcja celu nie przypisuje wartości tworzonym resztkom. Plan, który rozcina kilka
odcinków na wiele średnich resztek, może mieć mniejszy odpad niż plan optymalny, mimo że zużywa
więcej materiału. Przykład znaleziony podczas testów (rzaz 3, próg 300, resztki 1250/1400/2400/1600 +
4×3000, elementy 3×640, 2×800, 3×600): heurystyka zużywa 9650 mm (5 odcinków, odpad 24 mm,
4306 mm nowych resztek), branch and bound 5650 mm (3 odcinki, odpad 330 mm, bez nowych resztek,
2400 i 1600 oraz dwie sztangi 3000 zostają nietknięte). Wybieramy prostą, jednoznaczną funkcję celu
i pokazujemy w UI zarówno zużycie, jak i odpad oraz resztki każdej metody.

## 4. Heurystyka bazowa – first-fit decreasing (FFD)

1. Elementy sortujemy malejąco.
2. Element trafia do **pierwszego otwartego** odcinka, w którym się zmieści (z rzazem).
3. Gdy żaden nie pasuje – otwieramy **najkrótszy wolny** odcinek, w którym element się zmieści.
4. Gdy nie ma takiego odcinka – element zostaje nieprzydzielony (status `INFEASIBLE` heurystyki).

Złożoność `O(n·b)`, wynik natychmiastowy, ale bez gwarancji jakości (status `HEURISTIC`).

## 5. Metoda dokładniejsza – ograniczone branch and bound

Przeszukiwanie w głąb drzewa decyzji „element `i` → który odcinek”:

* elementy w kolejności malejącej długości,
* dla elementu próbujemy: każdy otwarty odcinek, w którym się mieści, albo otwarcie nowego wolnego
  odcinka,
* **rozwiązanie startowe** = wynik FFD (jeśli kompletny) – od początku mamy górne ograniczenie,
* **dolne ograniczenie** węzła: koszt otwartych odcinków + brakująca pojemność
  `max(0, suma pozostałych elementów − wolne miejsce w otwartych odcinkach)`; gdy deficyt > 0,
  co najmniej jeden nowy odcinek (koszt ≥ najkrótszy wolny). Gałąź jest odcinana, jeśli
  ograniczenie ≥ najlepszego znanego `(długość, liczba)`. Jeśli deficyt przekracza łączną długość
  wolnych odcinków – gałąź jest niewykonalna,
* **usuwanie symetrii**: nowe odcinki o tej samej długości są wymienne (próbujemy jeden), otwarte
  odcinki o identycznym stanie też, a elementy o tej samej długości przydzielamy w niemalejącej
  kolejności odcinków,
* szybki dowód braku materiału: element dłuższy niż najdłuższy odcinek albo suma elementów większa
  niż suma dostępnych odcinków.

Poprawność jest sprawdzana w testach porównaniem z **pełnym przeglądem** wszystkich przydziałów
na 360 losowych małych instancjach (`test_branch_and_bound_matches_exhaustive_search`).

Redukcja wejścia (bezstratna): z odcinków tej samej specyfikacji i długości bierzemy najwyżej tyle,
ile jest elementów tej specyfikacji – więcej i tak nie może zostać użytych.

## 6. Limity

| Limit | Domyślnie | Zmienna |
|---|---|---|
| węzły przeszukiwania | 300 000 | `OFFCUT_OPTIMIZER_MAX_NODES` |
| czas (łącznie dla wszystkich specyfikacji w projekcie) | 3 s | `OFFCUT_OPTIMIZER_TIME_LIMIT_S` |
| elementów w projekcie | 200 | `OFFCUT_MAX_PIECES_PER_PROJECT` (\*) |
| odcinków-kandydatów | 400 | `OFFCUT_MAX_STOCK_CANDIDATES` (\*) |

(\*) Ustawiane przy uruchomieniu backendu poza Docker Compose; `docker-compose.yml` przekazuje tylko
limity węzłów i czasu.

Pomiar (losowe instancje, odcinki 900–3000 mm, elementy 350–1100 mm, rzaz 3 mm, domyślne limity,
jeden rdzeń). Odtworzenie: `cd backend && uv run python -m scripts.benchmark_optimizer` – instancje są
deterministyczne, czasy zależą od komputera:

| Elementów | FFD [mm / odcinki] | B&B [mm / odcinki] | Status B&B | Czas |
|---|---|---|---|---|
| 10 | 7 800 / 5 | 6 600 / 3 | `OPTIMAL` (360 węzłów) | < 0,01 s |
| 20 | 15 600 / 11 | 13 200 / 6 | `BEST_FOUND` (limit węzłów) | 0,7 s |
| 40 | 30 000 / 19 | 28 800 / 18 | `BEST_FOUND` | 1,0 s |
| 80 | 63 300 / 45 | 62 100 / 44 | `BEST_FOUND` | 1,8 s |
| 200 | 145 200 / 81 | 145 200 / 81 | `BEST_FOUND` (brak poprawy) | 3,0 s |

Wniosek: dowód optymalności uzyskujemy dla małych projektów (rzędu kilkunastu elementów – typowy
projekt majsterkowicza). Dla większych B&B zwraca najlepszy plan znaleziony w limicie – nigdy gorszy
niż FFD, bo startuje od jego wyniku – i oznacza go jako `BEST_FOUND`, nie `OPTIMAL`.

## 7. Statusy wyniku

| Status | Znaczenie |
|---|---|
| `HEURISTIC` | plan z FFD, bez gwarancji jakości |
| `OPTIMAL` | przeszukiwanie B&B zakończone – plan optymalny **dla tej funkcji celu i tych odcinków** |
| `BEST_FOUND` | osiągnięto limit – najlepszy plan znaleziony w limicie, **bez dowodu optymalności** |
| `INFEASIBLE` | materiału na pewno nie wystarczy (B&B) / heurystyka nie przydzieliła wszystkich elementów (FFD) |
| `NO_SOLUTION_IN_LIMIT` | limit osiągnięty, zanim znaleziono jakikolwiek plan |

Przy kilku specyfikacjach status zbiorczy to najsłabszy ze statusów grup. W planie zapisujemy też
liczbę odwiedzonych węzłów, czas i dolne ograniczenie (`lower_bound_mm`).

## 8. Przykład porównania (dane demo „Regał na narzędzia”)

Sosna 40×20 mm, rzaz 3 mm, próg resztki 300 mm.
Magazyn: resztki 1250, 1900, 1400, 900 mm oraz 3 nowe listwy 3000 mm.
Zapotrzebowanie: 2 × 950 (słupek), 1 × 600 (poprzeczka), 3 × 560 (listwa nośna).

**Heurystyka FFD** – 4 odcinki, 5450 mm:

| Odcinek | Elementy | Rzaz | Pozostałość |
|---|---|---|---|
| 1250 | 950 | 3 | 297 – odpad |
| 1400 | 950 | 3 | 447 – resztka |
| 900 | 600 | 3 | 297 – odpad |
| 1900 | 560, 560, 560 | 9 | 211 – odpad |

**Branch and bound** (`OPTIMAL`, 96 węzłów) – 2 odcinki, 4900 mm:

| Odcinek | Elementy | Rzaz | Pozostałość |
|---|---|---|---|
| 1900 | 950, 600 | 6 | 344 – resztka |
| 3000 | 950, 560, 560, 560 | 12 | 358 – resztka |

Wynik: B&B zużywa **550 mm materiału mniej** i **2 odcinki mniej**, odpad spada z 823 mm do 18 mm,
a resztki 1250, 1400 i 900 mm zostają w magazynie nietknięte. Liczby są sprawdzone testem
`test_demo_case_branch_and_bound_beats_greedy` (wynik B&B zgodny z pełnym przeglądem) i testem
API `test_full_flow_login_demand_optimize_reserve_execute_remnants`.

### Większy przykład (dane demo „Stojak na drewno kominkowe”)

Świerk 45×45 mm, rzaz 3 mm, próg 300 mm. Magazyn: resztki 2100, 1300, 1100, 850, 700 mm i 5 nowych
kantówek 2700 mm. Zapotrzebowanie: 4 × 1150, 4 × 760, 3 × 520, 2 × 420 mm (13 elementów, 10 040 mm).

| Metoda | Zużycie | Odcinki | Odpad | Uwagi |
|---|---|---|---|---|
| FFD | 14 150 mm | 8 | 734 mm | m.in. cała nowa kantówka 2700 mm rozpoczęta dla jednego elementu 420 mm |
| B&B (`OPTIMAL`, 3257 węzłów) | 10 200 mm | 4 | 160 mm | 2100 = 1150 + 520 + 420; 2 × (2700 = 1150 + 760 + 760); 2700 = 1150 + 520 + 520 + 420 |

Oszczędność: 3950 mm materiału i 4 odcinki. Test: `test_larger_demo_case_branch_and_bound_saves_bars`.
Przy 13 elementach i 10 odcinkach przestrzeń przydziałów to 10¹³ – to przykład, którego nie da się
rozsądnie policzyć ręcznie ani kalkulatorem.

### Remis metod

Gdy obie metody znajdują plan o tej samej wartości funkcji celu, UI i API mówią to wprost
(„Obie metody dały plan o tej samej wartości funkcji celu”). W danych demo jest to projekt
„Wsporniki z profilu” (aluminium, 2 × 1000 + 1 × 150 mm, rzaz 2 mm): obie metody tną resztkę 2200 mm
(2 × 1000 + 150 + 2 cięcia między elementami = 2154 mm, cięcie końcowe 2 mm, pozostałość 44 mm
– poniżej progu, więc odpad planu = 6 mm rzazu + 44 mm = 50 mm).
Testy: `test_seed.py::test_demo_projects_give_documented_results` (dokładnie ten projekt) oraz
`test_both_methods_equal_is_reported_honestly` (inny przypadek remisu: 4 × 700 mm z listew 3000 mm).
