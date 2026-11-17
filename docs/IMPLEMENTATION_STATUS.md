# Stan implementacji (plik przekazania między sesjami)

Ostatnia aktualizacja: **wtorek 17.11.2026** (sesja 1, Europe/Warsaw).
Następna sesja: zacznij od przeczytania tego pliku i `git log`, potem uruchom testy.

## Co działa (sprawdzone)

* Backend FastAPI + PostgreSQL + Alembic – migracja `0001` od pustej bazy (upgrade/downgrade/upgrade,
  `alembic check` bez różnic).
* Domena: model rzazu, walidator planu, FFD, branch and bound (porównanie z pełnym przeglądem).
* REST API: auth (cookie HttpOnly + CSRF), role, izolacja warsztatów, magazyn, specyfikacje,
  projekty, zapotrzebowanie, optymalizacja, plan ręczny, rezerwacja, zwolnienie, wykonanie.
* Seed danych demo – idempotentny (sprawdzone dwukrotnym uruchomieniem).
* Obraz Docker backendu buduje się (w tym środowisku z dodatkowym certyfikatem proxy – patrz niżej).
* Dokumentacja: ALGORITHM, ERD (+png), API (+openapi.json), DEFENSE_NOTES, README.

## Testy

`cd backend && uv run pytest` → **72 passed** (PostgreSQL 16 w kontenerze na porcie 5433).

## W toku / do zrobienia (kolejność)

1. Frontend (React + TS + Vite) – w trakcie.
2. Test e2e Playwright: logowanie → zapotrzebowanie → optymalizacja → rezerwacja → wykonanie → resztka.
3. `docker compose up --build` od pustej bazy + seed + przejście scenariusza w przeglądarce.
4. Screenshoty do `docs/screenshots/`, `docs/DEMO.md`.
5. Push po każdym zweryfikowanym etapie.

## Istotne decyzje

* Funkcja celu: pokrycie → min. łączna długość zużytych odcinków → min. liczba odcinków.
* Plan: `DRAFT → RESERVED → EXECUTED`, zwolnienie `RESERVED → DRAFT`; rewizja projektu unieważnia plany.
* Rezerwacja = status odcinka + `reserved_plan_id` (bez osobnej tabeli), chroniona blokadami
  `FOR UPDATE`, warunkowym UPDATE i ograniczeniami CHECK/UNIQUE.
* Optymalizacja tworzy 2 plany (FFD i B&B) ze wspólnym `run_id`; plan niepełny nie jest zapisywany.
* Operator: tylko odczyt i zatwierdzenie wykonania.

## Uwagi o środowisku

* Proxy sesji przechwytuje TLS – `docker build` wymaga tu certyfikatu proxy. Repo zawiera czyste
  Dockerfile; weryfikacja używała wariantu ze scratchpada dodającego 2 linie z certyfikatem.

## Polecenia

```bash
docker compose -f docker-compose.test.yml up -d && (cd backend && uv run pytest)
cp .env.example .env && docker compose up --build -d && docker compose exec backend python -m app.seed
```

## Repozytorium

Gałąź `main`, wypchnięta do https://github.com/wokapala/offcut (publiczne). Tożsamość lokalna
(potwierdzona przez autora): `Wojciech Kapała <wokapala@gmail.com>`. Katalog `frontend/` jest w trakcie
pracy i nie jest jeszcze zacommitowany.
