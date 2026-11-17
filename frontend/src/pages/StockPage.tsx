import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, type MaterialSpec, type StockItem, type StockStatus } from '../api'
import { useAuth } from '../auth'
import { Badge, Card, Empty, ErrorAlert, Spinner } from '../components/ui'
import { useAction, useLoad } from '../hooks'
import { mm, stockStatusLabel, stockStatusTone } from '../labels'

const STATUS_FILTERS: { value: StockStatus | 'ALL'; label: string }[] = [
  { value: 'AVAILABLE', label: 'Dostępne' },
  { value: 'RESERVED', label: 'Zarezerwowane' },
  { value: 'CONSUMED', label: 'Zużyte' },
  { value: 'DISCARDED', label: 'Wycofane' },
  { value: 'ALL', label: 'Wszystkie' },
]

export default function StockPage() {
  const { workshop } = useAuth()
  const wid = workshop!.workshop_id
  const isOwner = workshop!.role === 'OWNER'

  // Filtry trzymamy w adresie URL (?status=…&spec=…&remnants=1) – można je linkować.
  const [params, setParams] = useSearchParams()
  const status = params.get('status') ?? 'AVAILABLE'
  const spec = params.get('spec') ?? ''
  const remnantsOnly = params.get('remnants') === '1'

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    setParams(next, { replace: true })
  }

  const materials = useLoad(() => api.materials(wid), [wid])
  const summary = useLoad(() => api.summary(wid), [wid])
  const stock = useLoad(() => {
    const q = new URLSearchParams({ status })
    if (spec) q.set('material_spec_id', spec)
    if (remnantsOnly) q.set('remnants_only', 'true')
    return api.stock(wid, q)
  }, [wid, status, spec, remnantsOnly])

  const discard = useAction()
  function onDiscard(item: StockItem) {
    if (!window.confirm(`Wycofać odcinek #${item.id} (${item.length_mm} mm) z magazynu?`)) return
    discard.run(async () => {
      await api.discardStock(item.id)
      stock.reload()
      summary.reload()
    })
  }

  function refreshAll() {
    stock.reload()
    summary.reload()
  }

  return (
    <>
      <div className="page-head">
        <h1>Magazyn</h1>
        {summary.data && (
          <div className="counters">
            {(['AVAILABLE', 'RESERVED', 'CONSUMED'] as const).map((s) => (
              <div key={s} className="counter">
                <span className="counter-value">{summary.data?.[s]?.count ?? 0}</span>
                <span className="counter-label">
                  {stockStatusLabel[s]} · {mm(summary.data?.[s]?.length_mm ?? 0)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <Card>
        <div className="filters">
          <label>
            Status
            <select value={status} onChange={(e) => setFilter('status', e.target.value === 'AVAILABLE' ? '' : e.target.value)}>
              {STATUS_FILTERS.map((f) => (
                <option key={f.value} value={f.value}>
                  {f.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Specyfikacja
            <select value={spec} onChange={(e) => setFilter('spec', e.target.value)}>
              <option value="">Wszystkie</option>
              {materials.data?.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>
          <label className="checkbox">
            <input type="checkbox" checked={remnantsOnly} onChange={(e) => setFilter('remnants', e.target.checked ? '1' : '')} />
            tylko resztki
          </label>
        </div>

        <ErrorAlert error={discard.error} onClose={discard.clearError} />
        <ErrorAlert error={stock.error} />
        {stock.loading && !stock.data ? (
          <Spinner />
        ) : stock.data && stock.data.length === 0 ? (
          <Empty>Brak odcinków dla wybranych filtrów.</Empty>
        ) : (
          stock.data && (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Specyfikacja</th>
                    <th className="num">Długość (mm)</th>
                    <th>Typ</th>
                    <th>Status</th>
                    <th>Pochodzenie</th>
                    <th>Etykieta</th>
                    {isOwner && <th />}
                  </tr>
                </thead>
                <tbody>
                  {stock.data.map((item) => (
                    <tr key={item.id} data-testid={`stock-row-${item.id}`}>
                      <td className="mono">#{item.id}</td>
                      <td>{item.spec_label}</td>
                      <td className="num">{item.length_mm}</td>
                      <td>{item.is_remnant ? 'Resztka' : 'Nowy odcinek'}</td>
                      <td>
                        <Badge tone={stockStatusTone[item.status]}>{stockStatusLabel[item.status]}</Badge>
                        {item.reserved_plan_id && (
                          <Link to={`/plans/${item.reserved_plan_id}`} className="small">
                            {' '}
                            plan #{item.reserved_plan_id}
                          </Link>
                        )}
                      </td>
                      <td>
                        <Origin item={item} />
                      </td>
                      <td>{item.label ?? <span className="muted">—</span>}</td>
                      {isOwner && (
                        <td className="actions">
                          {item.status === 'AVAILABLE' && (
                            <button type="button" className="btn btn-sm btn-ghost" disabled={discard.pending} onClick={() => onDiscard(item)}>
                              Wycofaj
                            </button>
                          )}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </Card>

      {isOwner && (
        <div className="grid-2">
          <AddStockForm wid={wid} materials={materials.data ?? []} onAdded={refreshAll} />
          <AddSpecForm wid={wid} onAdded={materials.reload} />
        </div>
      )}
    </>
  )
}

function Origin({ item }: { item: StockItem }) {
  if (!item.source_plan_id && !item.parent_stock_id) return <span className="muted">przyjęcie</span>
  return (
    <span className="small">
      {item.source_plan_id && <Link to={`/plans/${item.source_plan_id}`}>z planu #{item.source_plan_id}</Link>}
      {item.source_plan_id && item.parent_stock_id && ', '}
      {item.parent_stock_id && <>z odcinka #{item.parent_stock_id}</>}
    </span>
  )
}

function AddStockForm({ wid, materials, onAdded }: { wid: number; materials: MaterialSpec[]; onAdded: () => void }) {
  const [specId, setSpecId] = useState('')
  const [length, setLength] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [isRemnant, setIsRemnant] = useState(false)
  const [label, setLabel] = useState('')
  const [message, setMessage] = useState('')
  const action = useAction()

  function submit(e: FormEvent) {
    e.preventDefault()
    setMessage('')
    action.run(async () => {
      const created = await api.createStock(wid, {
        material_spec_id: Number(specId),
        length_mm: Number(length),
        quantity: Number(quantity),
        is_remnant: isRemnant,
        label: label.trim() || null,
      })
      setMessage(`Dodano ${created.length} odc.: ${created.map((s) => `#${s.id}`).join(', ')}`)
      setLength('')
      setLabel('')
      onAdded()
    })
  }

  return (
    <Card title="Przyjęcie na magazyn">
      <form onSubmit={submit} className="form-grid">
        <label className="span-2">
          Specyfikacja
          <select required value={specId} onChange={(e) => setSpecId(e.target.value)}>
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
          <input type="number" min={1} max={100000} required value={length} onChange={(e) => setLength(e.target.value)} />
        </label>
        <label>
          Ilość sztuk
          <input type="number" min={1} max={100} required value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </label>
        <label className="span-2">
          Etykieta (opcjonalnie)
          <input maxLength={120} value={label} onChange={(e) => setLabel(e.target.value)} />
        </label>
        <label className="checkbox span-2">
          <input type="checkbox" checked={isRemnant} onChange={(e) => setIsRemnant(e.target.checked)} />
          to jest resztka (już cięty odcinek)
        </label>
        <div className="span-2 form-actions">
          <button type="submit" className="btn btn-primary" disabled={action.pending}>
            {action.pending ? 'Zapisywanie…' : 'Dodaj odcinki'}
          </button>
          {message && <span className="ok-text">{message}</span>}
        </div>
      </form>
      <ErrorAlert error={action.error} onClose={action.clearError} />
    </Card>
  )
}

function AddSpecForm({ wid, onAdded }: { wid: number; onAdded: () => void }) {
  const [material, setMaterial] = useState('')
  const [section, setSection] = useState('')
  const action = useAction()

  function submit(e: FormEvent) {
    e.preventDefault()
    action.run(async () => {
      await api.createMaterial(wid, { material, section })
      setMaterial('')
      setSection('')
      onAdded()
    })
  }

  return (
    <Card title="Nowa specyfikacja materiału">
      <p className="muted small">Materiał i przekrój – np. „Sosna” i „40x20 mm”. Cięcie możliwe tylko w obrębie tej samej specyfikacji.</p>
      <form onSubmit={submit} className="form-grid">
        <label>
          Materiał
          <input required maxLength={80} value={material} onChange={(e) => setMaterial(e.target.value)} placeholder="Sosna" />
        </label>
        <label>
          Przekrój
          <input required maxLength={80} value={section} onChange={(e) => setSection(e.target.value)} placeholder="40x20 mm" />
        </label>
        <div className="span-2 form-actions">
          <button type="submit" className="btn" disabled={action.pending}>
            {action.pending ? 'Zapisywanie…' : 'Dodaj specyfikację'}
          </button>
        </div>
      </form>
      <ErrorAlert error={action.error} onClose={action.clearError} />
    </Card>
  )
}
