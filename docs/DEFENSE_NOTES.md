# Notatki do obrony

## 1. Architektura – najważniejsze decyzje

* **Modularny monolit**: jeden backend (FastAPI), jedna baza (PostgreSQL), jeden frontend
  (React + TypeScript). Skala projektu nie uzasadnia mikroserwisów, kolejek ani cache.
* **Warstwy backendu**:
  `app/domain` – czysty Python: model rzazu, walidator planu, algorytmy (bez HTTP i bazy, testowalne
  jednostkowo) → `app/services` – reguły biznesowe i transakcje (planowanie, rezerwacja, wykonanie)
  → `app/api` – cienkie endpointy REST (walidacja wejścia, autoryzacja, serializacja).
* **SQLAlchemy 2 (sync) + Alembic**: jedna migracja tworzy cały schemat od pustej bazy; testy
  uruchamiają ją za każdym razem (`alembic upgrade head`), więc migracja jest testowana.
* **Długości w całkowitych milimetrach** – brak błędów zmiennoprzecinkowych w bilansie.
* **Sesja w cookie HttpOnly + CSRF double-submit** zamiast tokenu w `localStorage` – JavaScript
  nie ma dostępu do tokenu sesji (ochrona przed kradzieżą przez XSS), a CSRF blokuje nagłówek
  `X-CSRF-Token`, którego obca strona nie zna. Frontend i API są pod jednym originem (nginx), więc
  CORS jest ograniczony do jednego adresu.
* **Docker Compose**: `db` (healthcheck, wolumen) → `backend` (migracje przy starcie) → `frontend`
  (nginx serwuje SPA i przekazuje `/api` do backendu). Dane demo ładowane osobnym poleceniem.

## 2. Reguły biznesowe (gdzie w kodzie)

| Reguła | Gdzie | Test |
|---|---|---|
| zgodność materiału i przekroju | `validate_plan`, wybór kandydatów w `planning._candidate_stock`, złożony FK | `test_incompatible_material_*` |
| dodatnie długości i ilości, nieujemny rzaz | Pydantic + `CHECK` w bazie + `bar_balance` | `test_validation_errors`, `test_invalid_rows_rejected` |
| bilans: odcinek = elementy + rzaz + pozostałość | `bar_balance` (asercja) + `CHECK` planu | `test_cutting.py` |
| plan pokrywa całe zapotrzebowanie (dokładnie) | `validate_plan` | `test_incomplete_coverage_*`, `test_overproduction_*` |
| brak podwójnej rezerwacji odcinka | `workflow.reserve_plan` (blokady + warunkowy UPDATE + CHECK) | `test_double_reservation_*`, `test_concurrent_reservations_only_one_wins` |
| nieaktualny / niezarezerwowany plan nie może być wykonany | `revision` projektu, `_ensure_current`, stan planu | `test_stale_plan_*`, `test_execute_requires_reservation` |
| jednorazowe wykonanie mimo ponowienia | blokada planu, `UNIQUE(plan_id)` w `plan_executions` | `test_execute_retry_*`, `test_concurrent_execute_consumes_once` |
| atomowe zużycie i utworzenie resztek | jedna transakcja w `execute_plan` | `test_execution_rolls_back_completely_on_error` |
| resztka tylko powyżej progu | `bar_balance.usable_remnant`, `create_remnants` | `test_short_remainder_is_scrap_not_remnant` |
| izolacja warsztatów | `deps.load_scoped` / `workshop_access` – 404 dla cudzych zasobów | `test_other_workshop_is_invisible_also_by_direct_id` |
| ograniczenia operatora | `Access.require_owner` | `test_operator_role_limits` |

**Cykl stanów planu:** `DRAFT → RESERVED → EXECUTED`; jawne zwolnienie rezerwacji
`RESERVED → DRAFT` (odcinki wracają do `AVAILABLE`). Plan wykonany jest końcowy. Projekt może mieć
najwyżej jeden plan `RESERVED`/`EXECUTED` (częściowy indeks unikalny). Gdy plan jest zarezerwowany,
zapotrzebowanie i parametry projektu są zablokowane (409 `PROJECT_LOCKED`).

**Stany odcinka:** `AVAILABLE → RESERVED → CONSUMED`, `RESERVED → AVAILABLE` (zwolnienie),
`AVAILABLE → DISCARDED` (wycofanie z magazynu, historia zostaje).

**Unieważnianie planów:** każda zmiana zapotrzebowania, rzazu lub progu zwiększa `projects.revision`.
Plan pamięta `project_revision`; rezerwacja i wykonanie wymagają zgodności (409 `STALE_PLAN`),
UI pokazuje plakietkę „nieaktualny”.

## 3. Dlaczego to jest „advanced feature”

Optymalizacja rozkroju 1D to problem NP-trudny (uogólnienie bin packing). Projekt zawiera:
* **model fizyczny rzazu** z rozróżnieniem cięć między elementami, cięcia oddzielającego resztkę
  i dokładnego wykorzystania końca odcinka,
* **dwie metody na tych samych danych** – heurystykę FFD i ograniczone **branch and bound** z dolnym
  ograniczeniem, usuwaniem symetrii, limitem węzłów i czasu oraz rozwiązaniem startowym z FFD,
* **uczciwe statusy** (`OPTIMAL` tylko po pełnym przeszukaniu, `BEST_FOUND` przy limicie),
* **weryfikację obliczeniową**: B&B porównany z pełnym przeglądem na 360 losowych instancjach,
  przykład demo z wyliczoną oszczędnością (550 mm, 2 odcinki),
* **integrację z procesem**: plan → rezerwacja z blokadami → wykonanie → resztki z pochodzeniem
  w magazynie, a wynik jest używany przy kolejnych optymalizacjach.

Nie jest to CRUD ani dashboard – wynik zależy od algorytmu i zmienia stan magazynu.

## 4. Ochrona rezerwacji (jak nie zużyć materiału dwa razy)

1. Jedna transakcja na operację; błąd = `ROLLBACK` całości.
2. `SELECT … FOR UPDATE` w stałej kolejności: plan → projekt → odcinki rosnąco po id. Druga
   transakcja czeka na blokadę i po jej zwolnieniu widzi już nowy stan. Stała kolejność zapobiega
   zakleszczeniom.
3. Warunkowy `UPDATE stock_items … WHERE status = 'AVAILABLE'` z kontrolą liczby zmienionych wierszy.
4. Ograniczenia bazy niezależne od Pythona: `CHECK (status='RESERVED') = (reserved_plan_id IS NOT NULL)`,
   częściowy `UNIQUE(project_id)` dla planów aktywnych, `UNIQUE(plan_id)` w `plan_executions`.
5. Wykonanie jest idempotentne: drugi request czeka na blokadę planu, widzi `EXECUTED` i zwraca ten
   sam wynik (`already_executed: true`).

Testy współbieżności uruchamiają równolegle 2 rezerwacje tych samych odcinków i 3 wykonania tego
samego planu na prawdziwym PostgreSQL – wygrywa dokładnie jedna rezerwacja, wykonanie jest jedno.

## 5. Ograniczenia algorytmu (uczciwie)

* Funkcja celu nie wycenia tworzonych resztek – patrz przykład w `ALGORITHM.md` §3.
* B&B ma złożoność wykładniczą; przy dużych instancjach kończy się limitem i zwraca `BEST_FOUND`
  (bez dowodu optymalności). Dolne ograniczenie jest proste (pojemnościowe).
* Kolejność elementów na odcinku nie uwzględnia kierunku słojów, wad materiału ani tolerancji.
* Model zakłada równy, czysty koniec odcinka (bez cięcia wyrównującego na początku).
* Rezerwacja jest całym odcinkiem – nie rezerwujemy fragmentów.
* Brak kolejki zadań – optymalizacja działa synchronicznie w żądaniu (limit czasu 3 s).

## 6. Prawdopodobne pytania

**Dlaczego nie solver (OR-Tools/MILP)?** Własne B&B jest krótkie (ok. 140 linii z komentarzami), da się je wyjaśnić
linia po linii i zweryfikować pełnym przeglądem. Solver byłby dodatkową zależnością z mniej
przejrzystym modelem dla tej skali (do 200 elementów).

**Skąd pewność, że B&B jest poprawny?** Każdy wynik przechodzi przez ten sam walidator bilansu co
plan ręczny, a na małych instancjach wynik jest porównywany z pełnym przeglądem wszystkich przydziałów.

**Co się stanie, gdy dwie osoby jednocześnie zarezerwują ten sam odcinek?** Patrz §4 – druga
transakcja czeka na blokadę wiersza, potem dostaje 409 `STOCK_UNAVAILABLE` z listą odcinków.

**Co jeśli ktoś kliknie „Zatwierdź wykonanie” dwa razy?** Druga odpowiedź ma `already_executed: true`;
odcinki nie są zużywane drugi raz, resztki nie są duplikowane (`UNIQUE(plan_id)`).

**Co, gdy po wygenerowaniu planu zmieni się zapotrzebowanie?** `revision` rośnie, plan staje się
nieaktualny – rezerwacja/wykonanie zwracają 409 `STALE_PLAN`.

**Co, gdy odcinek z planu zostanie w międzyczasie wycofany lub użyty w innym projekcie?** Rezerwacja
zwraca 409 `STOCK_UNAVAILABLE` – trzeba wygenerować plan ponownie.

**Dlaczego 404, a nie 403 dla cudzego warsztatu?** Nie ujawniamy, że zasób o danym ID istnieje.

**Dlaczego JSONB w `input_snapshot`?** To tylko kopia wejścia algorytmu do audytu i odtworzenia
obliczeń. Relacje planu (odcinki, elementy) są w normalnych tabelach z kluczami obcymi.

**Jak liczony jest rzaz przy dokładnym dopasowaniu?** Gdy ostatni element kończy się na końcu
odcinka, nie ma cięcia końcowego: 2003 = 1000 + 3 + 1000 (jedno cięcie). Gdy zostaje materiał – jest
dodatkowe cięcie oddzielające resztkę. Gdy zostaje mniej niż rzaz – cięcie zjada resztę.

**Czym różni się resztka od odpadu?** Pozostałość ≥ progu projektu (domyślnie 300 mm) wraca do
magazynu jako nowy odcinek z pochodzeniem; krótsza jest odpadem. Odpad planu = rzaz + nieużyteczne
pozostałości.
