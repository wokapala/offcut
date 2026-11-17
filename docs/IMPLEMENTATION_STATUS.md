# Stan implementacji (plik przekazania między sesjami)

Ostatnia aktualizacja: **wtorek 17.11.2026** (sesja 1, Europe/Warsaw).
Następna sesja: przeczytaj ten plik, `git log`, uruchom testy i stos Compose.

## Podsumowanie

Cały planowany zakres został zaimplementowany i zweryfikowany w sesji 1 (dzień 1 z planu).
Pierwotny harmonogram (wt–pt) przewidywał rozłożenie prac na 4 dni; prace poszły szybciej, więc
historia Git pokazuje rzeczywisty stan – wszystkie commity z 17.11.2026. Kolejne dni: przegląd,
ewentualne poprawki po własnym przejściu demo, przygotowanie PDF do oddania.

## Co działa (sprawdzone)

* Backend FastAPI + PostgreSQL + Alembic – migracja od pustej bazy (upgrade / downgrade / upgrade,
  `alembic check` bez różnic; migracja uruchamiana przez testy i przy starcie kontenera).
* Domena: model rzazu, wspólny walidator planu, FFD, branch and bound.
* REST API: auth (cookie HttpOnly + CSRF), role, izolacja warsztatów, magazyn, specyfikacje,
  projekty, zapotrzebowanie, optymalizacja, plan ręczny (API), rezerwacja, zwolnienie, wykonanie.
* Frontend React + TS: logowanie, magazyn, projekty, zapotrzebowanie, wynik z porównaniem metod,
  schemat rozkroju, plan z rezerwacją / zwolnieniem / wykonaniem, obsługa błędów 409.
* Docker Compose: `db` (healthcheck, wolumen) → `backend` (migracje) → `frontend` (nginx + proxy `/api`).
* Seed demo – idempotentny (2 uruchomienia → 3 konta, 12 odcinków, 3 projekty).

## Co sprawdzono i jak

| Sprawdzenie | Wynik |
|---|---|
| `cd backend && uv run pytest` (PostgreSQL 16, port 5433) | **72 passed** |
| `cd frontend && npm run build` | OK (tsc + vite, 0 błędów) |
| `docker compose up` od pustej bazy (obrazy zbudowane z Dockerfile z repo + certyfikat proxy sandboxa) | db/backend healthy, frontend działa, `/api/health` ok, deep link SPA 200, Swagger 200 |
| start bez danych demo | aplikacja działa, logowanie kontem demo odrzucone (dane demo niewymagane) |
| `npx playwright test` na stosie Compose | **1 passed** – logowanie → zapotrzebowanie → optymalizacja → rezerwacja → wykonanie → resztki |
| scenariusz `docs/DEMO.md` w przeglądarce (skrypt Playwright) | zgodny: 5450 vs 4900 mm, konflikt 409 w drugiej karcie, operator wykonuje plan, resztki 344 i 358 mm |
| render diagramu ERD (Mermaid) | OK – `docs/erd.png` |

## Znane problemy / ograniczenia

* W tym środowisku (proxy przechwytujące TLS) `docker build` wymaga dodania certyfikatu proxy –
  weryfikacja używała wariantu Dockerfile ze scratchpada (+2 linie: COPY certyfikatu i
  `PIP_CERT` / `NODE_EXTRA_CA_CERTS`). Dockerfile w repo jest czysty; **nie sprawdzono** budowania
  na zwykłej maszynie bez proxy – warto zrobić `docker compose up --build` u siebie przed oddaniem.
* Funkcja celu nie wycenia tworzonych resztek (opisane w ALGORITHM.md).
* B&B dowodzi optymalności dla małych projektów (~10–15 elementów), większe → `BEST_FOUND`.
* Sesja JWT bezstanowa – wylogowanie usuwa cookie, ale token ważny do wygaśnięcia (12 h);
  brak limitu prób logowania.
* UI nie ma edycji pozycji zapotrzebowania (dodaj/usuń), planu ręcznego ani zarządzania członkami
  (dostępne przez API).

## Kolejne zadania (kolejność)

1. Samodzielne przejście `docs/DEMO.md` na własnym komputerze (`docker compose up --build`).
2. Ewentualne poprawki UX po własnym przejściu demo.
3. PDF do oddania (opis + screenshoty z `docs/screenshots/`) – jeśli wymagany.
4. Nagranie / próba demonstracji 3–5 min.

## Istotne decyzje

* Funkcja celu: pokrycie → min. łączna długość zużytych odcinków → min. liczba odcinków.
* Plan: `DRAFT → RESERVED → EXECUTED`, zwolnienie `RESERVED → DRAFT`; rewizja projektu unieważnia plany.
* Rezerwacja = status odcinka + `reserved_plan_id` (bez osobnej tabeli), chroniona blokadami
  `FOR UPDATE`, warunkowym UPDATE i ograniczeniami CHECK/UNIQUE.
* Optymalizacja tworzy 2 plany (FFD i B&B) ze wspólnym `run_id`; plan niepełny nie jest zapisywany.
* Operator: tylko odczyt i zatwierdzenie wykonania.
* Frontend: bez bibliotek UI; schemat cięcia budowany wyłącznie z liczb z API.

## Polecenia

```bash
docker compose -f docker-compose.test.yml up -d && (cd backend && uv run pytest)
cp .env.example .env && docker compose up --build -d && docker compose exec backend python -m app.seed
cd frontend && npx playwright test
```

## Repozytorium

https://github.com/wokapala/offcut (publiczne), gałąź `main`. Tożsamość lokalna (potwierdzona przez
autora): `Wojciech Kapała <wokapala@gmail.com>`; podpisywanie commitów wyłączone lokalnie.
