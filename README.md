# Offcut — optymalizacja cięcia materiałów i wykorzystania resztek

Aplikacja webowa dla majsterkowiczów i małych warsztatów. Na podstawie fizycznych odcinków w magazynie
(nowych listew i resztek z wcześniejszych prac) oraz zapotrzebowania (długość × liczba sztuk) wylicza
plan cięcia z uwzględnieniem **szerokości rzazu**, porównuje **heurystykę zachłanną** z dokładniejszym
**branch and bound**, pokazuje plan jako schemat, a po zatwierdzeniu wykonania aktualizuje magazyn
i zapisuje użyteczne resztki.

Projekt indywidualny z przedmiotu ZTPAI (Politechnika Krakowska, zima 2026/27).

## Funkcjonalności

* logowanie (cookie HttpOnly + CSRF), role **właściciel** i **operator** warsztatu, izolacja warsztatów,
* ewidencja odcinków i resztek – każdy fizyczny odcinek ma własne ID i historię (pochodzenie resztki),
* specyfikacje materiałów (materiał + przekrój) i zgodność materiałowa przy planowaniu,
* projekty cięcia: zapotrzebowanie (specyfikacja, długość, liczba sztuk), rzaz, próg użytecznej resztki,
* **optymalizacja rozkroju 1D**: FFD vs branch and bound na tych samych danych, statusy wyniku,
  limity obliczeń, raport braku materiału,
* graficzny schemat cięcia (elementy, rzaz, resztka/odpad) i porównanie metod,
* rezerwacja materiału z ochroną przed podwójną rezerwacją (blokady w PostgreSQL),
* zatwierdzanie wykonania – idempotentne, atomowe zużycie odcinków i zapis resztek do magazynu,
* unieważnianie planów po zmianie zapotrzebowania lub parametrów,
* plan ręczny przez API (ten sam walidator bilansu co algorytmy).

## Stack

| Warstwa | Technologie |
|---|---|
| Backend | Python 3.13, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, argon2-cffi, PyJWT |
| Baza | PostgreSQL 16 |
| Frontend | React 19, TypeScript, Vite, react-router |
| Testy | pytest (na PostgreSQL), Playwright (przepływ w przeglądarce) |
| Uruchomienie | Docker Compose (PostgreSQL + backend + nginx z frontendem) |

Zależności są zablokowane: `backend/uv.lock` (+ `backend/requirements.txt` z hashami dla obrazu Docker),
`frontend/package-lock.json`.

## Uruchomienie (Docker Compose)

Wymagania: Docker z Compose v2.

```bash
cp .env.example .env
```

W `.env` ustaw własne `POSTGRES_PASSWORD` i `OFFCUT_SECRET_KEY`
(np. `python -c "import secrets; print(secrets.token_urlsafe(48))"`). Następnie:

```bash
docker compose up --build -d
```

| Usługa | Adres |
|---|---|
| aplikacja (frontend) | http://localhost:8080 |
| dokumentacja API (Swagger UI) | http://localhost:8080/api/docs |
| healthcheck API | http://localhost:8080/api/health |

Port zmienisz zmienną `OFFCUT_HTTP_PORT` w `.env`. Backend i baza nie są publikowane na hoście –
ruch do `/api` przechodzi przez nginx kontenera `frontend`.

### Migracje i dane demo

Migracje Alembic uruchamiają się automatycznie przy każdym starcie kontenera `backend`
(`alembic upgrade head`, od pustej bazy). Aplikacja startuje **bez** danych demo – można
zarejestrować własny warsztat na ekranie logowania (lub `POST /api/auth/register`).

Dane demonstracyjne ładuje się jawnie jednym poleceniem (bezpieczne do ponownego uruchomienia –
nie duplikuje danych):

```bash
docker compose exec backend python -m app.seed
```

Pełny reset bazy (usuwa wolumen z danymi):

```bash
docker compose down -v
```

### Konta demonstracyjne (tylko lokalne dane demo)

Hasło dla wszystkich: `Demo1234!`

| E-mail | Rola | Warsztat |
|---|---|---|
| `wlasciciel@offcut.demo` | właściciel | Warsztat Demo |
| `operator@offcut.demo` | operator | Warsztat Demo |
| `obcy@offcut.demo` | właściciel | Stolarnia Obca (do pokazania izolacji) |

Dane demo zawierają projekt „Regał na narzędzia”, w którym branch and bound zużywa 4900 mm materiału
zamiast 5450 mm z heurystyki, projekt z remisem metod i projekt z brakiem materiału.
Scenariusz prezentacji: `docs/DEMO.md` (w przygotowaniu).

## Testy

Backend – testy działają na **prawdziwym PostgreSQL** (transakcje, blokady, ograniczenia), nie na SQLite:

```bash
docker compose -f docker-compose.test.yml up -d
```

```bash
cd backend && uv sync && uv run pytest
```

Baza testowa nasłuchuje na porcie 5433 (inny adres: `OFFCUT_TEST_DATABASE_URL`). Schemat jest
tworzony migracjami Alembic przy każdym uruchomieniu testów.

Zakres: model rzazu i bilans, walidator planu, obie metody (w tym porównanie B&B z pełnym przeglądem
na losowych instancjach), brak materiału, niezgodny materiał, limity, logowanie i CSRF, role,
izolacja warsztatów (także po bezpośrednim ID), pełny przepływ, konflikt i współbieżność rezerwacji,
ponowienie wykonania, wycofanie transakcji przy błędzie, ograniczenia bazy.

Przepływ w przeglądarce (Playwright) – w przygotowaniu (stan: [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md)).

## Funkcja zaawansowana: optymalizacja rozkroju 1D

* **Model rzazu**: cięcia między elementami, cięcie oddzielające resztkę, brak cięcia przy dokładnym
  wykorzystaniu końca odcinka; bilans `odcinek = elementy + rzaz + pozostałość` w całkowitych mm.
* **Funkcja celu**: (1) całe zapotrzebowanie, (2) minimalna łączna długość zużytych odcinków,
  (3) minimalna liczba odcinków.
* **Heurystyka bazowa**: first-fit decreasing.
* **Metoda dokładniejsza**: branch and bound startujące od wyniku FFD, z dolnym ograniczeniem
  pojemnościowym, usuwaniem symetrii i limitem węzłów/czasu.
* **Statusy**: `OPTIMAL` tylko po pełnym przeszukaniu; przy limicie `BEST_FOUND`
  („najlepszy znaleziony w limicie”); `INFEASIBLE` przy braku materiału.

Szczegóły, przykłady i ograniczenia: [`docs/ALGORITHM.md`](docs/ALGORITHM.md).

## Dokumentacja

| Dokument | Zawartość |
|---|---|
| [`docs/ALGORITHM.md`](docs/ALGORITHM.md) | model rzazu, funkcja celu, algorytmy, limity, statusy, przykład |
| [`docs/ERD.md`](docs/ERD.md) | diagram ERD i ograniczenia bazy |
| [`docs/API.md`](docs/API.md) + Swagger | kluczowe operacje, uprawnienia, błędy |
| `docs/DEMO.md` | scenariusz demonstracji 3–5 min (w przygotowaniu) |
| [`docs/DEFENSE_NOTES.md`](docs/DEFENSE_NOTES.md) | decyzje, reguły biznesowe, pytania |
| [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md) | stan prac i weryfikacji |

## Struktura

```
backend/
  app/domain/      model rzazu, walidator planu, FFD i branch and bound (czysty Python)
  app/services/    planowanie, rezerwacja, wykonanie (transakcje i blokady)
  app/api/         endpointy REST
  app/models.py    model relacyjny (SQLAlchemy)
  alembic/         migracje
  tests/           pytest (PostgreSQL)
frontend/          React + TypeScript (Vite), nginx w obrazie produkcyjnym
docs/              dokumentacja
```

## Ograniczenia

* Funkcja celu nie wycenia tworzonych resztek (opis i przykład w `ALGORITHM.md`).
* Duże instancje kończą się limitem obliczeń (`BEST_FOUND`); limit 200 elementów na projekt.
* Brak resetu hasła, zarządzania kontem i zaproszeń e-mail (członków dodaje właściciel przez API).
* Plan ręczny dostępny tylko przez API (bez edytora w UI).
* Optymalizacja działa synchronicznie w żądaniu HTTP.
