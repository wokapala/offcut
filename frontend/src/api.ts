// Klient REST API backendu Offcut + typy odwzorowane z backend/app/schemas.py.
// Wszystkie adresy są względne (/api/...): w dev przekierowuje je Vite, w produkcji nginx.

export type Role = 'OWNER' | 'OPERATOR'
export type StockStatus = 'AVAILABLE' | 'RESERVED' | 'CONSUMED' | 'DISCARDED'
export type ProjectState = 'OPEN' | 'RESERVED' | 'EXECUTED'
export type PlanStatus = 'DRAFT' | 'RESERVED' | 'EXECUTED'
export type Method = 'GREEDY' | 'BRANCH_AND_BOUND' | 'MANUAL'
export type SolverStatus = 'HEURISTIC' | 'OPTIMAL' | 'BEST_FOUND' | 'INFEASIBLE' | 'NO_SOLUTION_IN_LIMIT' | 'MANUAL'

export interface Membership { workshop_id: number; workshop_name: string; role: Role }
export type EventType =
  | 'STOCK_RECEIVED'
  | 'STOCK_DISCARDED'
  | 'OPTIMIZATION_FINISHED'
  | 'PLAN_RESERVED'
  | 'PLAN_RELEASED'
  | 'PLAN_EXECUTED'

export interface WorkshopEvent {
  id: number
  type: EventType
  message: string
  actor: string | null
  data: Record<string, unknown>
  created_at: string
}

export interface EventPage { items: WorkshopEvent[]; total: number; limit: number; offset: number }

export interface Me { id: number; email: string; full_name: string; memberships: Membership[] }

export interface MaterialSpec { id: number; material: string; section: string; label: string }

export interface StockItem {
  id: number
  material_spec_id: number
  spec_label: string
  length_mm: number
  status: StockStatus
  is_remnant: boolean
  label: string | null
  reserved_plan_id: number | null
  parent_stock_id: number | null
  source_execution_id: number | null
  source_plan_id: number | null
  created_at: string
  consumed_at: string | null
}

export interface DemandItem {
  id: number
  material_spec_id: number
  spec_label: string
  length_mm: number
  quantity: number
  label: string | null
}

export interface Project {
  id: number
  workshop_id: number
  name: string
  kerf_mm: number
  min_remnant_mm: number
  revision: number
  state: ProjectState
  active_plan_id: number | null
  created_at: string
  demand_items: DemandItem[]
}

export interface ProjectListItem {
  id: number
  name: string
  state: ProjectState
  kerf_mm: number
  min_remnant_mm: number
  demand_lines: number
  piece_count: number
  created_at: string
}

export interface PlanPiece { demand_item_id: number | null; length_mm: number; label: string | null }

export interface PlanBar {
  stock_item_id: number
  spec_label: string
  stock_length_mm: number
  stock_is_remnant: boolean
  stock_label: string | null
  cut_count: number
  kerf_loss_mm: number
  remainder_mm: number
  usable_remnant: boolean
  pieces: PlanPiece[]
}

export interface Execution { id: number; executed_at: string; executed_by: string; remnant_stock_ids: number[] }

export interface Plan {
  id: number
  project_id: number
  run_id: string | null
  method: Method
  status: PlanStatus
  solver_status: SolverStatus
  is_current: boolean
  project_revision: number
  kerf_mm: number
  min_remnant_mm: number
  total_stock_mm: number
  stock_count: number
  pieces_mm: number
  kerf_loss_mm: number
  usable_remnant_mm: number
  scrap_mm: number
  waste_mm: number
  lower_bound_mm: number | null
  nodes: number
  elapsed_ms: number
  created_at: string
  reserved_at: string | null
  executed_at: string | null
  bars: PlanBar[]
  execution: Execution | null
}

export interface Shortage {
  material_spec_id: number
  spec_label: string
  piece_count: number
  pieces_mm: number
  longest_piece_mm: number
  available_count: number
  available_mm: number
  longest_available_mm: number
  message: string
}

export interface MethodResult {
  method: Method
  status: SolverStatus
  plan: Plan | null
  unplaced_count: number
  nodes: number
  elapsed_ms: number
}

export interface OptimizeResult {
  run_id: string
  greedy: MethodResult
  branch_and_bound: MethodResult
  comparison: {
    stock_saved_mm: number | null
    bars_saved: number | null
    waste_saved_mm: number | null
    verdict: string
  }
  shortages: Shortage[]
}

export interface ExecuteResult { plan: Plan; already_executed: boolean; remnants: StockItem[] }

export type Summary = Partial<Record<StockStatus, { count: number; length_mm: number }>>

/** Błąd API w jednolitym formacie backendu: {detail, code, problems}. */
export class ApiError extends Error {
  status: number
  code: string
  problems: string[]

  constructor(status: number, detail: string, code: string, problems: string[]) {
    super(detail)
    this.status = status
    this.code = code
    this.problems = problems
  }
}

let onUnauthorized: () => void = () => {}

/** AuthProvider rejestruje tu reakcję na 401 (wygasła sesja => ekran logowania). */
export function setUnauthorizedHandler(handler: () => void) {
  onUnauthorized = handler
}

function csrfToken(): string {
  const match = document.cookie.split('; ').find((c) => c.startsWith('offcut_csrf='))
  return match ? decodeURIComponent(match.slice('offcut_csrf='.length)) : ''
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-CSRF-Token'] = csrfToken()

  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      method,
      headers,
      credentials: 'same-origin',
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, 'Brak połączenia z serwerem. Sprawdź, czy backend działa.', 'NETWORK', [])
  }

  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/auth/')) onUnauthorized()
    throw new ApiError(
      res.status,
      data?.detail ?? `Błąd serwera (HTTP ${res.status})`,
      data?.code ?? 'HTTP_ERROR',
      Array.isArray(data?.problems) ? data.problems : [],
    )
  }
  return data as T
}

const get = <T>(path: string) => request<T>('GET', path)
const post = <T>(path: string, body?: unknown) => request<T>('POST', path, body)

export const api = {
  login: (email: string, password: string) => post<{ user: Me; csrf_token: string }>('/auth/login', { email, password }),
  logout: () => post<void>('/auth/logout'),
  me: () => get<Me>('/auth/me'),

  materials: (wid: number) => get<MaterialSpec[]>(`/workshops/${wid}/materials`),
  createMaterial: (wid: number, body: { material: string; section: string }) =>
    post<MaterialSpec>(`/workshops/${wid}/materials`, body),

  stock: (wid: number, params: URLSearchParams) => get<StockItem[]>(`/workshops/${wid}/stock?${params}`),
  createStock: (
    wid: number,
    body: { material_spec_id: number; length_mm: number; quantity: number; is_remnant: boolean; label: string | null },
  ) => post<StockItem[]>(`/workshops/${wid}/stock`, body),
  stockItem: (id: number) => get<StockItem>(`/stock/${id}`),
  discardStock: (id: number) => request<StockItem>('DELETE', `/stock/${id}`),
  summary: (wid: number) => get<Summary>(`/workshops/${wid}/summary`),
  events: (wid: number, params: URLSearchParams) => get<EventPage>(`/workshops/${wid}/events?${params}`),

  projects: (wid: number) => get<ProjectListItem[]>(`/workshops/${wid}/projects`),
  createProject: (wid: number, body: { name: string; kerf_mm: number; min_remnant_mm: number }) =>
    post<Project>(`/workshops/${wid}/projects`, body),
  project: (id: number) => get<Project>(`/projects/${id}`),
  updateProject: (id: number, body: { name?: string; kerf_mm?: number; min_remnant_mm?: number }) =>
    request<Project>('PATCH', `/projects/${id}`, body),
  addDemand: (
    projectId: number,
    body: { material_spec_id: number; length_mm: number; quantity: number; label: string | null },
  ) => post<Project>(`/projects/${projectId}/demand`, body),
  updateDemand: (id: number, body: { length_mm: number; quantity: number; label: string | null }) =>
    request<Project>('PATCH', `/demand/${id}`, body),
  deleteDemand: (id: number) => request<Project>('DELETE', `/demand/${id}`),
  optimize: (projectId: number) => post<OptimizeResult>(`/projects/${projectId}/optimize`),
  projectPlans: (projectId: number) => get<Plan[]>(`/projects/${projectId}/plans`),

  plan: (id: number) => get<Plan>(`/plans/${id}`),
  reservePlan: (id: number) => post<Plan>(`/plans/${id}/reserve`),
  releasePlan: (id: number) => post<Plan>(`/plans/${id}/release`),
  executePlan: (id: number) => post<ExecuteResult>(`/plans/${id}/execute`),
}
