import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type MaterialSpec, type OptimizeResult, type Plan, type Project } from '../api'
import { useAuth } from '../auth'
import OptimizeResultView from '../components/OptimizeResultView'
import { Alert, Badge, Card, Empty, ErrorAlert, Spinner } from '../components/ui'
import { useAction, useLoad } from '../hooks'
import { dateTime, methodLabel, mm, planStatusLabel, projectStateLabel, solverStatusLabel, stateTone } from '../labels'

export default function ProjectPage() {
  const id = Number(useParams().id)
  const { roleIn } = useAuth()
  const project = useLoad(() => api.project(id), [id])
  const plans = useLoad(() => api.projectPlans(id), [id])
  const wid = project.data?.workshop_id
  const materials = useLoad(() => (wid ? api.materials(wid) : Promise.resolve([])), [wid])
  const [result, setResult] = useState<OptimizeResult | null>(null)
  const optimize = useAction()

  if (project.loading && !project.data) return <Spinner />
  if (!project.data) return <ErrorAlert error={project.error} />

  const p = project.data
  const isOwner = roleIn(p.workshop_id) === 'OWNER'
  const editable = isOwner && p.state === 'OPEN'

  // Po każdej zmianie projektu stary wynik optymalizacji jest nieaktualny – chowamy go.
  function onProjectChanged(updated: Project) {
    project.setData(updated)
    setResult(null)
    plans.reload()
  }

  function runOptimize() {
    optimize.run(async () => {
      setResult(null)
      setResult(await api.optimize(id))
      plans.reload()
    })
  }

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/projects" className="small">
            ← Projekty
          </Link>
          <h1>{p.name}</h1>
          <div className="head-badges">
            <Badge tone={stateTone[p.state]} testId="project-state">
              {projectStateLabel[p.state]}
            </Badge>
            <span className="muted small">utworzony {dateTime(p.created_at)}</span>
          </div>
        </div>
      </div>

      {p.state !== 'OPEN' && (
        <Alert tone={p.state === 'EXECUTED' ? 'success' : 'info'} title={p.state === 'EXECUTED' ? 'Projekt wykonany' : 'Materiał zarezerwowany'}>
          Edycja projektu jest zablokowana.{' '}
          {p.active_plan_id && <Link to={`/plans/${p.active_plan_id}`}>Przejdź do aktywnego planu #{p.active_plan_id}</Link>}
        </Alert>
      )}

      <div className="grid-side">
        <ParamsCard key={`${p.id}-${p.revision}`} project={p} editable={editable} onSaved={onProjectChanged} />
        <DemandCard project={p} materials={materials.data ?? []} editable={editable} onChanged={onProjectChanged} />
      </div>

      {isOwner && p.state === 'OPEN' && (
        <div className="optimize-bar">
          <button
            type="button"
            className="btn btn-primary btn-lg"
            onClick={runOptimize}
            disabled={optimize.pending || p.demand_items.length === 0}
            data-testid="optimize"
          >
            {optimize.pending ? 'Optymalizacja…' : 'Optymalizuj rozkrój'}
          </button>
          <span className="muted small">Heurystyka FFD i branch and bound liczą plan dla tych samych danych.</span>
        </div>
      )}
      <ErrorAlert error={optimize.error} onClose={optimize.clearError} />
      {optimize.pending && <Spinner label="Liczenie planów rozkroju…" />}
      {result && <OptimizeResultView key={result.run_id} result={result} canReserve={editable} />}

      <PlansCard plans={plans.data} loading={plans.loading} />
    </>
  )
}

function ParamsCard({ project, editable, onSaved }: { project: Project; editable: boolean; onSaved: (p: Project) => void }) {
  const [kerf, setKerf] = useState(String(project.kerf_mm))
  const [minRemnant, setMinRemnant] = useState(String(project.min_remnant_mm))
  const action = useAction()
  const changed = Number(kerf) !== project.kerf_mm || Number(minRemnant) !== project.min_remnant_mm

  function submit(e: FormEvent) {
    e.preventDefault()
    action.run(async () => {
      onSaved(await api.updateProject(project.id, { kerf_mm: Number(kerf), min_remnant_mm: Number(minRemnant) }))
    })
  }

  return (
    <Card title="Parametry cięcia">
      <form onSubmit={submit} className="form-stack">
        <label>
          Rzaz – szerokość cięcia (mm)
          <input type="number" min={0} max={50} required disabled={!editable} value={kerf} onChange={(e) => setKerf(e.target.value)} />
        </label>
        <label>
          Minimalna użyteczna resztka (mm)
          <input
            type="number"
            min={0}
            max={100000}
            required
            disabled={!editable}
            value={minRemnant}
            onChange={(e) => setMinRemnant(e.target.value)}
          />
        </label>
        {editable && (
          <>
            <p className="muted small">Zmiana parametrów unieważnia wcześniej wygenerowane plany.</p>
            <button type="submit" className="btn" disabled={!changed || action.pending}>
              {action.pending ? 'Zapisywanie…' : 'Zapisz parametry'}
            </button>
          </>
        )}
      </form>
      <ErrorAlert error={action.error} onClose={action.clearError} />
      <p className="muted small">Rewizja projektu: {project.revision}</p>
    </Card>
  )
}

function DemandCard(props: { project: Project; materials: MaterialSpec[]; editable: boolean; onChanged: (p: Project) => void }) {
  const { project, materials, editable, onChanged } = props
  const [specId, setSpecId] = useState('')
  const [length, setLength] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [label, setLabel] = useState('')
  const action = useAction()
  const items = project.demand_items

  function submit(e: FormEvent) {
    e.preventDefault()
    action.run(async () => {
      onChanged(
        await api.addDemand(project.id, {
          material_spec_id: Number(specId),
          length_mm: Number(length),
          quantity: Number(quantity),
          label: label.trim() || null,
        }),
      )
      setLength('')
      setQuantity('1')
      setLabel('')
    })
  }

  function remove(demandId: number) {
    action.run(async () => onChanged(await api.deleteDemand(demandId)))
  }

  // Edycja w wierszu: długość, liczba sztuk i etykieta (zmiana specyfikacji = usuń i dodaj pozycję).
  const [edit, setEdit] = useState<{ id: number; length: string; quantity: string; label: string } | null>(null)

  function saveEdit(e: FormEvent) {
    e.preventDefault()
    if (!edit) return
    action.run(async () => {
      onChanged(
        await api.updateDemand(edit.id, {
          length_mm: Number(edit.length),
          quantity: Number(edit.quantity),
          label: edit.label.trim() || null,
        }),
      )
      setEdit(null)
    })
  }

  const total = items.reduce((acc, d) => acc + d.length_mm * d.quantity, 0)

  return (
    <Card title="Zapotrzebowanie">
      {items.length === 0 ? (
        <Empty>Dodaj zapotrzebowanie – elementy, które trzeba wyciąć.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Specyfikacja</th>
                <th className="num">Długość</th>
                <th className="num">Sztuk</th>
                <th>Etykieta</th>
                {editable && <th />}
              </tr>
            </thead>
            <tbody>
              {items.map((d) =>
                edit?.id === d.id ? (
                  <tr key={d.id} data-testid={`demand-row-${d.id}`} className="editing-row">
                    <td>{d.spec_label}</td>
                    <td className="num">
                      <input form="demand-edit" type="number" min={1} max={100000} required value={edit.length}
                        onChange={(e) => setEdit({ ...edit, length: e.target.value })} data-testid="edit-length" aria-label="Długość (mm)" />
                    </td>
                    <td className="num">
                      <input form="demand-edit" type="number" min={1} max={500} required value={edit.quantity}
                        onChange={(e) => setEdit({ ...edit, quantity: e.target.value })} data-testid="edit-quantity" aria-label="Sztuk" />
                    </td>
                    <td>
                      <input form="demand-edit" maxLength={120} value={edit.label}
                        onChange={(e) => setEdit({ ...edit, label: e.target.value })} aria-label="Etykieta" />
                    </td>
                    <td className="actions">
                      <form id="demand-edit" onSubmit={saveEdit} />
                      <button type="submit" form="demand-edit" className="btn btn-sm btn-primary" disabled={action.pending} data-testid="edit-save">
                        Zapisz
                      </button>
                      <button type="button" className="btn btn-sm btn-ghost" onClick={() => setEdit(null)}>
                        Anuluj
                      </button>
                    </td>
                  </tr>
                ) : (
                  <tr key={d.id} data-testid={`demand-row-${d.id}`}>
                    <td>{d.spec_label}</td>
                    <td className="num">{mm(d.length_mm)}</td>
                    <td className="num">{d.quantity}</td>
                    <td>{d.label ?? <span className="muted">—</span>}</td>
                    {editable && (
                      <td className="actions">
                        <button type="button" className="btn btn-sm btn-ghost" disabled={action.pending}
                          onClick={() => setEdit({ id: d.id, length: String(d.length_mm), quantity: String(d.quantity), label: d.label ?? '' })}
                          data-testid={`demand-edit-${d.id}`}>
                          Edytuj
                        </button>
                        <button type="button" className="btn btn-sm btn-ghost" disabled={action.pending} onClick={() => remove(d.id)}>
                          Usuń
                        </button>
                      </td>
                    )}
                  </tr>
                ),
              )}
            </tbody>
            <tfoot>
              <tr>
                <td>Razem</td>
                <td className="num">{mm(total)}</td>
                <td className="num">{items.reduce((acc, d) => acc + d.quantity, 0)}</td>
                <td colSpan={editable ? 2 : 1} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {editable && (
        <form onSubmit={submit} className="form-row demand-form">
          <label className="grow">
            Specyfikacja
            <select required value={specId} onChange={(e) => setSpecId(e.target.value)} data-testid="demand-spec">
              <option value="">— wybierz —</option>
              {materials.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Długość (mm)
            <input type="number" min={1} max={100000} required value={length} onChange={(e) => setLength(e.target.value)} data-testid="demand-length" />
          </label>
          <label className="narrow">
            Sztuk
            <input type="number" min={1} max={500} required value={quantity} onChange={(e) => setQuantity(e.target.value)} data-testid="demand-quantity" />
          </label>
          <label className="grow">
            Etykieta
            <input maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="np. półka" />
          </label>
          <button type="submit" className="btn" disabled={action.pending} data-testid="demand-add">
            Dodaj
          </button>
        </form>
      )}
      <ErrorAlert error={action.error} onClose={action.clearError} />
    </Card>
  )
}

function PlansCard({ plans, loading }: { plans: Plan[] | null; loading: boolean }) {
  return (
    <Card title="Wygenerowane plany">
      {loading && !plans ? (
        <Spinner />
      ) : !plans || plans.length === 0 ? (
        <Empty>Brak planów – uruchom optymalizację.</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Plan</th>
                <th>Metoda</th>
                <th>Wynik solvera</th>
                <th>Status</th>
                <th className="num">Zużyty materiał</th>
                <th className="num">Odcinki</th>
                <th>Utworzony</th>
              </tr>
            </thead>
            <tbody>
              {plans.map((pl) => (
                <tr key={pl.id} className={pl.is_current ? '' : 'stale'}>
                  <td>
                    <Link to={`/plans/${pl.id}`}>Plan #{pl.id}</Link>
                  </td>
                  <td>{methodLabel[pl.method]}</td>
                  <td className="small">{solverStatusLabel[pl.solver_status]}</td>
                  <td>
                    <Badge tone={stateTone[pl.status]}>{planStatusLabel[pl.status]}</Badge>{' '}
                    {!pl.is_current && <Badge tone="warning">nieaktualny</Badge>}
                  </td>
                  <td className="num">{mm(pl.total_stock_mm)}</td>
                  <td className="num">{pl.stock_count}</td>
                  <td className="small">{dateTime(pl.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
