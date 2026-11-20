# Dokumentacja API

Pełna, interaktywna specyfikacja OpenAPI (Swagger UI) jest generowana z kodu:

* po uruchomieniu przez Docker Compose: **http://localhost:8080/api/docs**
* plik: [`docs/openapi.json`](openapi.json) (eksport z `app.openapi()`)

Wszystkie ścieżki zaczynają się od `/api`. Długości są liczbami całkowitymi w milimetrach.

## Uwierzytelnianie i CSRF

1. `POST /api/auth/login` `{"email", "password"}` → cookie `offcut_session` (HttpOnly, SameSite=Lax)
   + cookie `offcut_csrf` + w treści `csrf_token`.
2. Każde żądanie `POST/PATCH/DELETE` wymaga nagłówka `X-CSRF-Token: <csrf_token>`.
3. W Swagger UI: wykonaj logowanie, skopiuj `csrf_token`, kliknij **Authorize** i wklej go w pole
   `X-CSRF-Token` (cookie sesji przeglądarka wysyła sama).

## Format błędów

```json
{"detail": "Część odcinków z planu nie jest już dostępna …", "code": "STOCK_UNAVAILABLE",
 "problems": ["Odcinek #6 (3000 mm) ma status RESERVED"]}
```

| HTTP | Kody | Kiedy |
|---|---|---|
| 401 | `NOT_AUTHENTICATED`, `BAD_CREDENTIALS` | brak/wygasła sesja, złe hasło |
| 403 | `OWNER_REQUIRED`, `CSRF_FAILED` | operacja tylko dla właściciela, brak tokenu CSRF |
| 404 | `NOT_FOUND` | brak zasobu **lub zasób z cudzego warsztatu** (nie ujawniamy istnienia) |
| 409 | `STOCK_UNAVAILABLE`, `STALE_PLAN`, `PROJECT_LOCKED`, `PLAN_NOT_RESERVED`, `PLAN_NOT_DRAFT`, `SPEC_EXISTS`, `SPEC_IN_USE`, `EMAIL_TAKEN`, `STOCK_NOT_AVAILABLE`, `RESERVATION_INCONSISTENT` | konflikt stanu |
| 422 | `VALIDATION_ERROR`, `INVALID_PLAN`, `EMPTY_DEMAND`, `PROBLEM_TOO_LARGE` | błędne dane, plan niezgodny z bilansem |

## Uprawnienia

| Operacja | Właściciel | Operator | Inny warsztat |
|---|---|---|---|
| odczyt magazynu, projektów, planów | ✔ | ✔ | 404 |
| materiały, przyjęcie / wycofanie odcinków | ✔ | 403 | 404 |
| projekty, zapotrzebowanie, optymalizacja, plan ręczny | ✔ | 403 | 404 |
| rezerwacja i zwolnienie rezerwacji | ✔ | 403 | 404 |
| zatwierdzenie wykonania | ✔ | ✔ | 404 |
| dodanie członka warsztatu | ✔ | 403 | 404 |

## Kluczowe operacje

### `POST /api/projects/{id}/optimize`
Uruchamia **obie** metody (FFD i branch and bound) na tych samych danych: dostępnych odcinkach
zgodnych materiałowo, rzazie i progu resztki projektu. Kompletne wyniki zapisuje jako plany `DRAFT`
ze wspólnym `run_id`.

```json
{
  "run_id": "…",
  "greedy":           {"method": "GREEDY", "status": "HEURISTIC", "plan": {"id": 1, "total_stock_mm": 5450, "stock_count": 4, …}, "unplaced_count": 0, "nodes": 0, "elapsed_ms": 0},
  "branch_and_bound": {"method": "BRANCH_AND_BOUND", "status": "OPTIMAL", "plan": {"id": 2, "total_stock_mm": 4900, "stock_count": 2, …}, "nodes": 96, …},
  "comparison": {"stock_saved_mm": 550, "bars_saved": 2, "waste_saved_mm": 805, "verdict": "Branch and bound zużywa o 550 mm materiału mniej …"},
  "shortages": []
}
```

Brak materiału to poprawny wynik obliczeń (HTTP 200): `status: "INFEASIBLE"`, `plan: null`
i opis w `shortages[]`. Błędy: 409 `PROJECT_LOCKED` (projekt ma rezerwację/wykonanie),
422 `EMPTY_DEMAND`, `PROBLEM_TOO_LARGE`.

### `GET /api/plans/{id}`
Plan z odcinkami (`bars[]`): długość odcinka, elementy po kolei, `cut_count`, `kerf_loss_mm`,
`remainder_mm`, `usable_remnant`; statystyki planu (`total_stock_mm = pieces_mm + kerf_loss_mm +
usable_remnant_mm + scrap_mm`, `waste_mm`), `is_current` (false po zmianie projektu).

### `POST /api/plans/{id}/reserve`
`DRAFT → RESERVED`. W jednej transakcji blokuje wiersze planu, projektu i odcinków
(`SELECT … FOR UPDATE`, kolejność po id) i ustawia odcinki na `RESERVED`.
409: `STOCK_UNAVAILABLE` (odcinek zajęty/zużyty/wycofany – z listą w `problems`),
`STALE_PLAN` (zapotrzebowanie lub parametry zmieniły się), `PROJECT_LOCKED` (inny plan projektu
jest już zarezerwowany). Ponowienie dla zarezerwowanego planu zwraca 200 bez zmian.

### `POST /api/plans/{id}/release`
`RESERVED → DRAFT`, odcinki wracają do `AVAILABLE`. Wykonanego planu nie da się zwolnić (409).

### `POST /api/plans/{id}/execute`
`RESERVED → EXECUTED` atomowo: odcinki → `CONSUMED`, użyteczne pozostałości → nowe odcinki
`AVAILABLE` z `parent_stock_id` i `source_execution_id`. **Idempotentne**: ponowienie zwraca ten sam
wynik z `already_executed: true` i niczego nie zużywa drugi raz. 409 `PLAN_NOT_RESERVED`,
`STALE_PLAN`.

### `POST /api/projects/{id}/plans/manual`
Plan ręczny `{"bars": [{"stock_item_id": 7, "demand_item_ids": [3, 3, 1]}]}` – sprawdzany tym samym
walidatorem bilansu co wyniki algorytmów. 422 `INVALID_PLAN` z listą problemów (niezgodny materiał,
elementy się nie mieszczą z rzazem, niepełne pokrycie). Dostępny tylko przez API.

### Magazyn
`GET /api/workshops/{id}/stock?status=AVAILABLE|RESERVED|CONSUMED|DISCARDED|ALL&material_spec_id=&remnants_only=`
– każdy odcinek osobno, z pochodzeniem (`parent_stock_id`, `source_plan_id`).
`POST /api/workshops/{id}/stock` `{"material_spec_id", "length_mm", "quantity", "is_remnant", "label"}`
tworzy `quantity` osobnych odcinków. `DELETE /api/stock/{id}` wycofuje odcinek (`DISCARDED`) – historia
zostaje.
