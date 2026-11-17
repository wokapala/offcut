// Polskie etykiety wartości zwracanych przez API.
import type { Method, PlanStatus, ProjectState, Role, SolverStatus, StockStatus } from './api'

export const roleLabel: Record<Role, string> = { OWNER: 'Właściciel', OPERATOR: 'Operator' }

export const stockStatusLabel: Record<StockStatus, string> = {
  AVAILABLE: 'Dostępny',
  RESERVED: 'Zarezerwowany',
  CONSUMED: 'Zużyty',
  DISCARDED: 'Wycofany',
}

export const projectStateLabel: Record<ProjectState, string> = {
  OPEN: 'Otwarty',
  RESERVED: 'Zarezerwowany',
  EXECUTED: 'Wykonany',
}

export const planStatusLabel: Record<PlanStatus, string> = {
  DRAFT: 'Szkic',
  RESERVED: 'Zarezerwowany',
  EXECUTED: 'Wykonany',
}

export const methodLabel: Record<Method, string> = {
  GREEDY: 'Heurystyka FFD (bazowa)',
  BRANCH_AND_BOUND: 'Branch and bound',
  MANUAL: 'Plan ręczny',
}

export const solverStatusLabel: Record<SolverStatus, string> = {
  HEURISTIC: 'Heurystyka – bez gwarancji jakości',
  OPTIMAL: 'Optymalny',
  BEST_FOUND: 'Najlepszy znaleziony w limicie',
  INFEASIBLE: 'Brak materiału / brak planu',
  NO_SOLUTION_IN_LIMIT: 'Brak planu w limicie',
  MANUAL: 'Plan ręczny',
}

/** Kolor plakietki (klasa CSS badge-<tone>) dla każdego statusu. */
export type Tone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'

export const stockStatusTone: Record<StockStatus, Tone> = {
  AVAILABLE: 'success',
  RESERVED: 'warning',
  CONSUMED: 'neutral',
  DISCARDED: 'danger',
}

export const stateTone: Record<ProjectState | PlanStatus, Tone> = {
  OPEN: 'accent',
  DRAFT: 'neutral',
  RESERVED: 'warning',
  EXECUTED: 'success',
}

export const solverTone: Record<SolverStatus, Tone> = {
  HEURISTIC: 'neutral',
  OPTIMAL: 'success',
  BEST_FOUND: 'accent',
  INFEASIBLE: 'danger',
  NO_SOLUTION_IN_LIMIT: 'danger',
  MANUAL: 'neutral',
}

export function mm(value: number): string {
  return `${value.toLocaleString('pl-PL')} mm`
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString('pl-PL', { dateStyle: 'medium', timeStyle: 'short' })
}
