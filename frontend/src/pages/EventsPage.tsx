import { useState } from 'react'
import { api, type EventType } from '../api'
import { useAuth } from '../auth'
import { Badge, Card, Empty, ErrorAlert, Spinner } from '../components/ui'
import { useLoad } from '../hooks'
import { dateTime, type Tone } from '../labels'

// Dziennik zdarzeń warsztatu – wpisy tworzy asynchronicznie backend (zdarzenia domenowe).
// Paginacja po stronie API: limit + offset, łączna liczba w polu `total`.

const PAGE_SIZE = 10

const EVENT_LABELS: Record<EventType, { label: string; tone: Tone }> = {
  STOCK_RECEIVED: { label: 'Przyjęcie', tone: 'neutral' },
  STOCK_DISCARDED: { label: 'Wycofanie', tone: 'warning' },
  OPTIMIZATION_FINISHED: { label: 'Optymalizacja', tone: 'accent' },
  PLAN_RESERVED: { label: 'Rezerwacja', tone: 'warning' },
  PLAN_RELEASED: { label: 'Zwolnienie', tone: 'neutral' },
  PLAN_EXECUTED: { label: 'Wykonanie', tone: 'success' },
}

export default function EventsPage() {
  const { workshop } = useAuth()
  const wid = workshop!.workshop_id
  const [type, setType] = useState<EventType | ''>('')
  const [page, setPage] = useState(0)

  const events = useLoad(() => {
    const q = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) })
    if (type) q.set('type', type)
    return api.events(wid, q)
  }, [wid, type, page])

  const total = events.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <>
      <div className="page-head">
        <h1>Historia warsztatu</h1>
      </div>
      <Card>
        <div className="filters">
          <label>
            Typ zdarzenia
            <select
              value={type}
              data-testid="events-type"
              onChange={(e) => {
                setType(e.target.value as EventType | '')
                setPage(0)
              }}
            >
              <option value="">Wszystkie</option>
              {Object.entries(EVENT_LABELS).map(([value, { label }]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <ErrorAlert error={events.error} />
        {events.loading && !events.data ? (
          <Spinner />
        ) : total === 0 ? (
          <Empty>Brak zdarzeń. Pojawią się po przyjęciu materiału, optymalizacji, rezerwacji lub wykonaniu planu.</Empty>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Kiedy</th>
                    <th>Typ</th>
                    <th>Opis</th>
                    <th>Kto</th>
                  </tr>
                </thead>
                <tbody>
                  {events.data!.items.map((e) => (
                    <tr key={e.id} data-testid={`event-row-${e.id}`}>
                      <td className="nowrap">{dateTime(e.created_at)}</td>
                      <td>
                        <Badge tone={EVENT_LABELS[e.type].tone}>{EVENT_LABELS[e.type].label}</Badge>
                      </td>
                      <td>{e.message}</td>
                      <td>{e.actor ?? <span className="muted">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pager" data-testid="events-pager">
              <button type="button" className="btn btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                ← Poprzednia
              </button>
              <span className="muted small">
                Strona {page + 1} z {pages} · {total} zdarzeń
              </span>
              <button type="button" className="btn btn-sm" disabled={page + 1 >= pages} onClick={() => setPage(page + 1)}>
                Następna →
              </button>
            </div>
          </>
        )}
      </Card>
    </>
  )
}
