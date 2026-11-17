import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type MethodResult, type OptimizeResult, type Plan } from '../api'
import { useAction } from '../hooks'
import { methodLabel, mm, solverStatusLabel, solverTone } from '../labels'
import CutDiagram from './CutDiagram'
import PlanMetrics from './PlanMetrics'
import { Alert, Badge, ErrorAlert } from './ui'

/** Który plan jest lepszy wg funkcji celu: mniej materiału, przy remisie mniej odcinków. */
function betterMethod(a: Plan | null, b: Plan | null): string | null {
  if (!a || !b) return a?.method ?? b?.method ?? null
  if (a.total_stock_mm !== b.total_stock_mm) return a.total_stock_mm < b.total_stock_mm ? a.method : b.method
  if (a.stock_count !== b.stock_count) return a.stock_count < b.stock_count ? a.method : b.method
  return null // remis
}

export default function OptimizeResultView({ result, canReserve }: { result: OptimizeResult; canReserve: boolean }) {
  const navigate = useNavigate()
  const reserve = useAction()
  const results = [result.greedy, result.branch_and_bound]
  const best = betterMethod(result.greedy.plan, result.branch_and_bound.plan)
  const withPlan = results.filter((r) => r.plan)
  const [shown, setShown] = useState(best ?? withPlan[0]?.method ?? null)
  const shownPlan = results.find((r) => r.method === shown)?.plan ?? null

  function onReserve(plan: Plan) {
    reserve.run(async () => {
      await api.reservePlan(plan.id)
      navigate(`/plans/${plan.id}`)
    })
  }

  return (
    <section className="result" data-testid="optimize-result">
      <div className="verdict" data-testid="verdict">
        {result.comparison.verdict}
      </div>
      {result.shortages.map((s) => (
        <Alert key={s.material_spec_id} tone="warning" title={`Za mało materiału: ${s.spec_label}`}>
          {s.message}
        </Alert>
      ))}
      <ErrorAlert error={reserve.error} onClose={reserve.clearError} />

      <div className="result-grid">
        {results.map((r) => (
          <ResultCard
            key={r.method}
            result={r}
            isBest={best === r.method}
            canReserve={canReserve}
            pending={reserve.pending}
            onReserve={onReserve}
          />
        ))}
      </div>

      {shownPlan && (
        <div className="card">
          <header className="card-head">
            <h2>Schemat rozkroju</h2>
            {withPlan.length > 1 && (
              <div className="segmented" role="tablist">
                {withPlan.map((r) => (
                  <button
                    key={r.method}
                    type="button"
                    role="tab"
                    aria-selected={shown === r.method}
                    className={shown === r.method ? 'active' : ''}
                    onClick={() => setShown(r.method)}
                  >
                    {methodLabel[r.method]}
                  </button>
                ))}
              </div>
            )}
          </header>
          <CutDiagram plan={shownPlan} />
        </div>
      )}
    </section>
  )
}

function ResultCard(props: {
  result: MethodResult
  isBest: boolean
  canReserve: boolean
  pending: boolean
  onReserve: (plan: Plan) => void
}) {
  const { result, isBest, canReserve, pending, onReserve } = props
  const plan = result.plan
  return (
    <article className={`card result-card ${isBest ? 'best' : ''}`} data-testid={`result-${result.method}`}>
      <header className="card-head">
        <h2>{methodLabel[result.method]}</h2>
        {isBest && <span className="best-tag">Lepszy plan</span>}
      </header>
      <Badge tone={solverTone[result.status]}>{solverStatusLabel[result.status]}</Badge>

      {plan ? (
        <>
          <PlanMetrics plan={plan} />
          {plan.lower_bound_mm !== null && result.method === 'BRANCH_AND_BOUND' && (
            <p className="muted small">Dolne ograniczenie zużycia: {mm(plan.lower_bound_mm)}</p>
          )}
          {canReserve && (
            <button
              type="button"
              className={`btn ${isBest ? 'btn-primary' : ''}`}
              disabled={pending}
              onClick={() => onReserve(plan)}
              data-testid={`reserve-${result.method}`}
            >
              Zarezerwuj ten plan
            </button>
          )}
        </>
      ) : (
        <div className="no-plan">
          <p>Brak planu pokrywającego całe zapotrzebowanie.</p>
          {result.unplaced_count > 0 && <p className="muted">Nieprzydzielone elementy: {result.unplaced_count}</p>}
          <p className="muted small">
            Węzły: {result.nodes.toLocaleString('pl-PL')} · czas: {result.elapsed_ms} ms
          </p>
        </div>
      )}
    </article>
  )
}
