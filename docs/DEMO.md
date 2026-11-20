# Scenariusz demonstracji (3–5 minut)

## Przygotowanie (przed prezentacją)

```bash
cp .env.example .env            # wartości domyślne wystarczą lokalnie
docker compose down -v          # świeża baza (usuwa dane!)
docker compose up --build -d
docker compose exec backend python -m app.seed
```

Otwórz http://localhost:8080. Drugą kartę zostaw na http://localhost:8080/api/docs (Swagger).
Konta demo (hasło `Demo1234!`): `wlasciciel@offcut.demo`, `operator@offcut.demo`, `obcy@offcut.demo`.

## Przebieg

| Czas | Krok | Co pokazać / powiedzieć | Oczekiwany wynik |
|---|---|---|---|
| 0:00 | Logowanie jako `wlasciciel@offcut.demo` | Sesja w cookie HttpOnly + token CSRF; role właściciel / operator | nagłówek: „Warsztat Demo”, „Anna Właścicielka”, plakietka „Właściciel” |
| 0:20 | **Magazyn** | Każdy odcinek ma własne ID; np. sosna 40×20: resztki 1250/1900/1400/900 mm i 3 nowe listwy 3000 mm | 20 dostępnych odcinków, 48 200 mm (sosna, aluminium, świerk) |
| 0:45 | **Projekty → „Regał na narzędzia”** | Zapotrzebowanie: 2×950, 1×600, 3×560 mm; rzaz 3 mm, próg resztki 300 mm | 6 elementów, 4180 mm |
| 1:05 | **Optymalizuj rozkrój** | Obie metody liczą na tych samych danych | FFD: 5450 mm, 4 odcinki, odpad 823 mm; B&B: **4900 mm, 2 odcinki, odpad 18 mm, status „Optymalny”** |
| 1:30 | Schemat rozkroju (przełącz FFD / B&B) | Paski: elementy, czerwony rzaz między elementami, cięcie końcowe, zielona resztka / szary odpad | B&B: 1900 → 950+600+resztka 344; 3000 → 950+3×560+resztka 358 |
| 2:00 | Wyjaśnienie algorytmu (poniżej) | FFD vs branch and bound, statusy | — |
| 2:30 | Na liście „Wygenerowane plany” otwórz plan FFD **w nowej karcie** (symulacja drugiego użytkownika), wróć do pierwszej karty i kliknij **Zarezerwuj ten plan** przy B&B | Odcinki przechodzą w stan zarezerwowany, projekt jest zablokowany | status planu „Zarezerwowany” |
| 2:45 | **Sytuacja błędna**: w drugiej karcie (plan FFD) kliknij **Zarezerwuj materiał** | Oba plany używają resztki 1900 mm – ochrona przed podwójną rezerwacją (blokady wierszy w PostgreSQL) | „Konflikt: Materiał niedostępny … Odcinek #2 (1900 mm) jest zarezerwowany” (409) |
| 3:05 | Wyloguj, zaloguj `operator@offcut.demo`, otwórz plan (link w banerze projektu), pokaż **Instrukcję cięcia** i przycisk „Drukuj instrukcję”, **Zatwierdź wykonanie** | Operator nie może planować ani rezerwować, może zatwierdzić wykonanie | status „Wykonany”, utworzone resztki **344 mm i 358 mm** |
| 3:35 | **Magazyn → tylko resztki** | Resztki mają pochodzenie („z planu #…, z odcinka #…”); odcinki 1900 i 3000 są zużyte | 2 nowe resztki dostępne do kolejnych projektów |
| 3:55 | Jako właściciel: projekt **„Stojak na drewno kominkowe”** → Optymalizuj | Większy problem (13 elementów, 10¹³ możliwych przydziałów) – „na kalkulatorze” się nie da | FFD: 14 150 mm, 8 odcinków; B&B: **10 200 mm, 4 odcinki**, „Optymalny” |
| 4:20 | Projekt **„Listwy przypodłogowe (za mało materiału)”** → Optymalizuj (jako właściciel) | Uczciwe raportowanie braku materiału | „Brak materiału / brak planu” + komunikat z wymaganą i dostępną długością |
| 4:40 | (opcjonalnie) Swagger `/api/docs` lub `obcy@offcut.demo` → `/projects/1` | Izolacja warsztatów – 404 również po bezpośrednim ID | „Nie znaleziono: projekt” |

Dodatkowo (jeśli jest czas): projekt „Wsporniki z profilu” – obie metody dają ten sam wynik
(resztka 2200 mm) i UI mówi to wprost, bez wskazywania „lepszej” metody.

## Algorytm w 30 sekund

* Rzaz: między elementami jedno cięcie; jeśli zostaje materiał – dodatkowe cięcie oddzielające
  resztkę; przy dokładnym dopasowaniu końca tego cięcia nie ma. Bilans: odcinek = elementy + rzaz +
  pozostałość (całkowite mm).
* Cel: pokryć całe zapotrzebowanie → minimalna łączna długość zużytych odcinków → mniej odcinków.
* FFD (bazowa): elementy od najdłuższego, każdy do pierwszego pasującego odcinka, inaczej najkrótszy
  wolny odcinek. Szybka, bez gwarancji.
* Branch and bound: przeszukuje przydziały, startuje od wyniku FFD, odcina gałęzie dolnym
  ograniczeniem i symetriami. `Optymalny` tylko po pełnym przeszukaniu; przy limicie
  „najlepszy znaleziony w limicie”. Poprawność sprawdzona testami z pełnym przeglądem.

## Zrzuty ekranu

`docs/screenshots/` – wykonane z działającej aplikacji (Docker Compose, dane demo):

| Plik | Ekran |
|---|---|
| `01-logowanie.png` | logowanie z kontami demo |
| `02-magazyn.png` | magazyn odcinków i resztek |
| `03-projekty.png` | lista projektów |
| `04-wynik-porownanie.png` | porównanie metod (najważniejszy ekran) |
| `05-projekt-pelny.png` | projekt: parametry, zapotrzebowanie, wynik, schemat |
| `06-plan-zarezerwowany.png` | plan po rezerwacji |
| `07-plan-wykonany.png` | plan wykonany z utworzonymi resztkami |
| `08-resztki-w-magazynie.png` | resztki z pochodzeniem w magazynie |
| `09-brak-materialu.png` | brak materiału |
| `10-konflikt-rezerwacji.png` | konflikt rezerwacji (409) |
| `11-wiekszy-projekt-porownanie.png` | większy projekt (13 elementów) – porównanie metod |
| `12-instrukcja-do-druku.png` | plan w widoku do druku z instrukcją cięcia |
