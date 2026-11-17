import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type Plan, type StockItem } from '../api'
import { useAuth } from '../auth'
import CutDiagram from '../components/CutDiagram'
import PlanMetrics from '../components/PlanMetrics'
import { Alert, Badge, Card, ErrorAlert, Spinner } from '../components/ui'
import { useAction, useLoad } from '../hooks'
import { dateTime, methodLabel, mm, planStatusLabel, solverStatusLabel, solverTone, stateTone } from '../labels'

export default function PlanPage() {
  const id = Number(useParams().id)
  const { roleIn } = useAuth()
  const plan = useLoad(() => api.plan(id), [id])
  const projectId = plan.data?.project_id
  const project = useLoad(() => (projectId ? api.project(projectId) : Promise.resolve(null)), [projectId])
  const [remnants, setRemnants] = useState<StockItem[] | null>(null)
  const action = useAction()

  // Resztki wykonanego planu: przy wejściu na stronę dociągamy je po ID z historii wykonania.
  const remnantIds = plan.data?.execution?.remnant_stock_ids.join(',') ?? ''
  useEffect(() => {
    if (!remnantIds) return setRemnants(null)
    Promise.all(remnantIds.split(',').map((rid) => api.stockItem(Number(rid))))
      .then(setRemnants)
      .catch(() => setRemnants(null))
  }, [remnantIds])

  if (plan.loading && !plan.data) return <Spinner />
  if (!plan.data) return <ErrorAlert error={plan.error} />

  const p = plan.data
  const role = project.data ? roleIn(project.data.workshop_id) : null
  const isOwner = role === 'OWNER'

  function update(next: Plan) {
    plan.setData(next)
    project.reload()
  }

  const reserve = () => action.run(async () => update(await api.reservePlan(p.id)))
  const release = () => action.run(async () => update(await api.releasePlan(p.id)))
  const execute = () => {
    if (!window.confirm('Zatwierdzić wykonanie planu? Odcinki zostaną oznaczone jako zużyte, a użyteczne resztki trafią do magazynu.')) return
    action.run(async () => {
      const res = await api.executePlan(p.id)
      setRemnants(res.remnants)
      update(res.plan)
    })
  }

  return (
    <>
      <div className="page-head">
        <div>
          {project.data && (
            <Link to={`/projects/${project.data.id}`} className="small">
              ← {project.data.name}
            </Link>
          )}
          <h1>
            Plan #{p.id} · {methodLabel[p.method]}
          </h1>
          <div className="head-badges">
            <Badge tone={stateTone[p.status]} testId="plan-status">
              {planStatusLabel[p.status]}
            </Badge>
            <Badge tone={solverTone[p.solver_status]}>{solverStatusLabel[p.solver_status]}</Badge>
            <span className="muted small">
              rzaz {p.kerf_mm} mm · min. resztka {p.min_remnant_mm} mm · utworzony {dateTime(p.created_at)}
            </span>
          </div>
        </div>
        <div className="head-actions">
          {isOwner && p.status === 'DRAFT' && (
            <button type="button" className="btn btn-primary" onClick={reserve} disabled={action.pending} data-testid="reserve-plan">
              Zarezerwuj materiał
            </button>
          )}
          {isOwner && p.status === 'RESERVED' && (
            <button type="button" className="btn" onClick={release} disabled={action.pending} data-testid="release-plan">
              Zwolnij rezerwację
            </button>
          )}
          {role && p.status === 'RESERVED' && (
            <button type="button" className="btn btn-primary" onClick={execute} disabled={action.pending} data-testid="execute-plan">
              Zatwierdź wykonanie
            </button>
          )}
        </div>
      </div>

      {!p.is_current && p.status !== 'EXECUTED' && (
        <Alert tone="warning" title="Plan nieaktualny">
          Zapotrzebowanie lub parametry projektu zmieniły się po wygenerowaniu tego planu. Uruchom optymalizację ponownie.
        </Alert>
      )}
      {p.status === 'RESERVED' && (
        <Alert tone="info" title="Materiał zarezerwowany">
          Odcinki z planu są zablokowane dla innych projektów
          {p.reserved_at && ` od ${dateTime(p.reserved_at)}`}. Po pocięciu zatwierdź wykonanie.
        </Alert>
      )}
      <ErrorAlert error={action.error} onClose={action.clearError} />

      {p.execution && (
        <Card title="Wykonanie" className="execution-card">
          <p>
            Wykonanie zatwierdził(a) <strong>{p.execution.executed_by}</strong> · {dateTime(p.execution.executed_at)}
          </p>
          <h3>Utworzone resztki</h3>
          {p.execution.remnant_stock_ids.length === 0 ? (
            <p className="muted" data-testid="remnants">
              Plan nie zostawił użytecznych resztek.
            </p>
          ) : (
            <ul className="remnant-list" data-testid="remnants">
              {(remnants ?? p.execution.remnant_stock_ids.map((rid) => ({ id: rid, length_mm: null }))).map((r) => (
                <li key={r.id}>
                  <span className="mono">#{r.id}</span> {r.length_mm !== null && <strong>{mm(r.length_mm)}</strong>}
                </li>
              ))}
            </ul>
          )}
          <Link to="/stock?remnants=1">Zobacz resztki w magazynie →</Link>
        </Card>
      )}

      <Card title="Podsumowanie">
        <PlanMetrics plan={p} />
      </Card>
      <Card title="Schemat rozkroju">
        <CutDiagram plan={p} />
      </Card>
    </>
  )
}
