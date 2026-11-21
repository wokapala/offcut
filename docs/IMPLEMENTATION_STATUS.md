# Stan projektu

Stan na **21.11.2026**. Zakres ze zgłoszenia projektu jest zaimplementowany i sprawdzony.

## Co działa

* Backend FastAPI + PostgreSQL + Alembic – migracja tworzy schemat od pustej bazy i uruchamia się
  przy starcie kontenera.
* Domena: model rzazu, wspólny walidator planu, heurystyka FFD, branch and bound z limitami.
* REST API: logowanie (cookie HttpOnly + CSRF), role właściciel / operator, izolacja warsztatów,
  magazyn i specyfikacje materiałów, projekty i zapotrzebowanie, optymalizacja, plan ręczny (API),
  rezerwacja, zwolnienie rezerwacji, idempotentne wykonanie z zapisem resztek.
* Frontend React + TypeScript: logowanie, magazyn z filtrami, projekty, zapotrzebowanie (dodawanie,
  edycja, usuwanie), porównanie metod, schemat rozkroju, instrukcja cięcia do druku, rezerwacja i
  wykonanie planu, komunikaty konfliktów.
* Docker Compose: `db` (healthcheck, wolumen) → `backend` (migracje) → `frontend` (nginx + proxy `/api`).
* Dane demo – opcjonalne i idempotentne (3 konta, 4 projekty, 22 odcinki).
* System zdarzeń domenowych: zdarzenia publikowane po udanych operacjach, obsługiwane asynchronicznie
  (`BackgroundTasks`), zapisywane w dzienniku warsztatu (migracja `0002`) – zakładka **Historia**
  z paginacją i filtrem typu. Magazyn: paginacja `limit`/`offset` + `X-Total-Count`.
* CI w GitHub Actions.

## Jak sprawdzono

| Sprawdzenie | Wynik |
|---|---|
| `cd backend && uv run pytest` (PostgreSQL 16) | 85 passed |
| GitHub Actions (`.github/workflows/ci.yml`) | testy backendu, build frontendu i obrazów Docker – zielone |
| `cd frontend && npm run build` | bez błędów |
| `docker compose up` od pustej bazy | `db` i `backend` healthy, `/api/health` 200, Swagger 200 |
| start bez danych demo | aplikacja działa; logowanie kontem demo odrzucone |
| seed uruchomiony dwukrotnie | brak duplikatów |
| `npx playwright test` na stosie Compose | 1 passed – pełny przepływ od logowania do resztek w magazynie |
| scenariusz `docs/DEMO.md` w przeglądarce | zgodny – wszystkie oczekiwane wyniki |
| liczby w dokumentacji | sprawdzone testami i skryptem `backend/scripts/benchmark_optimizer.py` |

Obrazy Docker były budowane w środowisku z proxy przechwytującym TLS, gdzie potrzebny był dodatkowy
certyfikat CA (Dockerfile w repozytorium go nie zawiera). Na zwykłym komputerze należy potwierdzić
budowanie poleceniem `docker compose up --build`.

## Ograniczenia

* Funkcja celu nie wycenia tworzonych resztek (opis i przykład w `ALGORITHM.md`).
* B&B dowodzi optymalności dla małych projektów (rzędu kilkunastu elementów); większe kończą się
  limitem ze statusem `BEST_FOUND`.
* Sesja JWT jest bezstanowa – wylogowanie usuwa cookie, ale token jest ważny do wygaśnięcia (12 h);
  brak limitu prób logowania.
* Rejestracja, plan ręczny i dodawanie członków warsztatu są dostępne tylko przez API.
* Specyfikacji pozycji zapotrzebowania nie zmienia się w miejscu (usuń i dodaj pozycję).
* Optymalizacja działa synchronicznie w żądaniu HTTP.
* Dane demo służą tylko do lokalnej prezentacji: seed odnajduje warsztat po nazwie „Warsztat Demo”
  i używa jawnych haseł demo.
* Klucz sesji z `.env.example` wystarcza lokalnie (backend ostrzega o tym przy starcie); poza własnym
  komputerem trzeba ustawić własny losowy `OFFCUT_SECRET_KEY`.

## Najważniejsze decyzje

* Funkcja celu: pokrycie zapotrzebowania → min. łączna długość zużytych odcinków → min. liczba odcinków.
* Plan: `DRAFT → RESERVED → EXECUTED`, zwolnienie `RESERVED → DRAFT`; rewizja projektu unieważnia plany.
* Rezerwacja = status odcinka + `reserved_plan_id`, chroniona blokadami `FOR UPDATE`, warunkowym
  UPDATE i ograniczeniami CHECK/UNIQUE w bazie.
* Optymalizacja zapisuje 2 plany (FFD i B&B) ze wspólnym `run_id`; plan niepełny nie jest zapisywany.
* Operator: odczyt i zatwierdzenie wykonania.
* Frontend bez bibliotek UI; schemat i instrukcja cięcia budowane wyłącznie z liczb z API.

## Polecenia

```bash
docker compose -f docker-compose.test.yml up -d && (cd backend && uv run pytest)
cp .env.example .env && docker compose up --build -d && docker compose exec backend python -m app.seed
cd frontend && npx playwright test
```
