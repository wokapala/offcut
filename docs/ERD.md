# Diagram ERD

Diagram odpowiada migracji `backend/alembic/versions/0001_initial_schema.py` (sprawdzony z
`information_schema` bazy po `alembic upgrade head`). GitHub renderuje blok Mermaid automatycznie.

```mermaid
erDiagram
    users ||--o{ memberships : "należy do"
    workshops ||--o{ memberships : "ma członków"
    workshops ||--o{ material_specs : "definiuje"
    workshops ||--o{ stock_items : "magazyn"
    workshops ||--o{ projects : "prowadzi"
    material_specs ||--o{ stock_items : "specyfikacja odcinka"
    material_specs ||--o{ demand_items : "specyfikacja elementu"
    projects ||--o{ demand_items : "zapotrzebowanie"
    projects ||--o{ cutting_plans : "plany"
    cutting_plans ||--o{ plan_bars : "używa odcinków"
    stock_items ||--o{ plan_bars : "przydzielony w planach"
    plan_bars ||--o{ plan_pieces : "wycinane elementy"
    demand_items |o--o{ plan_pieces : "realizuje pozycję"
    cutting_plans ||--o| plan_executions : "wykonanie (max 1)"
    cutting_plans |o--o{ stock_items : "rezerwuje (reserved_plan_id)"
    plan_executions |o--o{ stock_items : "tworzy resztki (source_execution_id)"
    stock_items |o--o{ stock_items : "resztka z odcinka (parent_stock_id)"
    users ||--o{ projects : "utworzył"
    users ||--o{ cutting_plans : "utworzył"
    users ||--o{ plan_executions : "zatwierdził"

    users {
        int id PK
        varchar email UK
        varchar full_name
        varchar password_hash "argon2id"
        timestamptz created_at
    }
    workshops {
        int id PK
        varchar name
        timestamptz created_at
    }
    memberships {
        int id PK
        int user_id FK
        int workshop_id FK
        varchar role "OWNER | OPERATOR"
    }
    material_specs {
        int id PK
        int workshop_id FK
        varchar material
        varchar section
        timestamptz created_at
    }
    stock_items {
        int id PK
        int workshop_id FK
        int material_spec_id FK "złożony FK (spec, warsztat)"
        int length_mm "> 0"
        varchar status "AVAILABLE | RESERVED | CONSUMED | DISCARDED"
        bool is_remnant
        varchar label
        int reserved_plan_id FK "NOT NULL <=> RESERVED"
        int parent_stock_id FK
        int source_execution_id FK
        timestamptz created_at
        timestamptz consumed_at
    }
    projects {
        int id PK
        int workshop_id FK
        varchar name
        int kerf_mm ">= 0"
        int min_remnant_mm ">= 0"
        int revision "rośnie przy zmianie danych"
        int created_by_id FK
        timestamptz created_at
    }
    demand_items {
        int id PK
        int project_id FK
        int material_spec_id FK
        int length_mm "> 0"
        int quantity "> 0"
        varchar label
    }
    cutting_plans {
        int id PK
        int project_id FK
        int project_revision
        varchar run_id "wspólny dla porównywanych metod"
        varchar method "GREEDY | BRANCH_AND_BOUND | MANUAL"
        varchar status "DRAFT | RESERVED | EXECUTED"
        varchar solver_status
        int kerf_mm
        int min_remnant_mm
        int total_stock_mm "= pieces + kerf_loss + usable + scrap"
        int stock_count
        int pieces_mm
        int kerf_loss_mm
        int usable_remnant_mm
        int scrap_mm
        int lower_bound_mm
        int nodes
        int elapsed_ms
        jsonb input_snapshot
        int created_by_id FK
        timestamptz created_at
        timestamptz reserved_at
        timestamptz executed_at
    }
    plan_bars {
        int id PK
        int plan_id FK
        int stock_item_id FK
        int position
        int stock_length_mm
        int cut_count
        int kerf_loss_mm
        int remainder_mm
        bool usable_remnant
    }
    plan_pieces {
        int id PK
        int plan_bar_id FK
        int demand_item_id FK "SET NULL po usunięciu pozycji"
        int position
        int length_mm "> 0"
        varchar label
    }
    plan_executions {
        int id PK
        int plan_id FK, UK
        int executed_by_id FK
        timestamptz executed_at
    }
```

## Najważniejsze ograniczenia

| Tabela | Ograniczenie | Cel |
|---|---|---|
| `memberships` | `UNIQUE(user_id, workshop_id)`, `CHECK role IN (...)` | jedno członkostwo, znane role |
| `material_specs` | `UNIQUE(workshop_id, material, section)`, `UNIQUE(id, workshop_id)` | brak duplikatów; cel złożonego FK |
| `stock_items` | FK `(material_spec_id, workshop_id)` → `material_specs(id, workshop_id)` | odcinek nie może mieć specyfikacji z innego warsztatu |
| `stock_items` | `CHECK length_mm > 0`, `CHECK status IN (...)` | dodatnie długości, dozwolone stany |
| `stock_items` | `CHECK (status = 'RESERVED') = (reserved_plan_id IS NOT NULL)` | rezerwacja zawsze wskazuje plan |
| `stock_items` | `CHECK source_execution_id IS NULL OR is_remnant` | odcinek z wykonania jest resztką |
| `stock_items` | indeks `(workshop_id, material_spec_id, status)` | wyszukiwanie kandydatów do optymalizacji |
| `projects` | `CHECK kerf_mm >= 0`, `CHECK min_remnant_mm >= 0` | nieujemny rzaz i próg |
| `demand_items` | `CHECK length_mm > 0`, `CHECK quantity > 0` | dodatnie długości i liczby sztuk |
| `cutting_plans` | `CHECK total_stock_mm = pieces_mm + kerf_loss_mm + usable_remnant_mm + scrap_mm` | bilans długości planu |
| `cutting_plans` | częściowy `UNIQUE(project_id) WHERE status IN ('RESERVED','EXECUTED')` | najwyżej jeden aktywny plan projektu |
| `plan_bars` | `UNIQUE(plan_id, stock_item_id)`, `UNIQUE(plan_id, position)` | odcinek raz w planie |
| `plan_executions` | `UNIQUE(plan_id)` | plan wykonany najwyżej raz |

`input_snapshot` (JSONB) przechowuje tylko kopię wejścia algorytmu (długości, kandydaci, limity) do
audytu – relacje planu są w tabelach `plan_bars` i `plan_pieces`.
