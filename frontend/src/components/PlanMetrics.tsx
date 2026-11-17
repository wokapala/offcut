import type { Plan } from '../api'
import { mm } from '../labels'

/** Najważniejsze liczby planu – te same na ekranie wyniku i na stronie planu. */
export default function PlanMetrics({ plan }: { plan: Plan }) {
  const rows: [string, string][] = [
    ['Zużyty materiał', mm(plan.total_stock_mm)],
    ['Liczba odcinków', String(plan.stock_count)],
    ['Elementy', mm(plan.pieces_mm)],
    ['Rzaz', mm(plan.kerf_loss_mm)],
    ['Odpad (rzaz + nieużyteczne)', mm(plan.waste_mm)],
    ['Użyteczne resztki', mm(plan.usable_remnant_mm)],
    ['Węzły i czas', `${plan.nodes.toLocaleString('pl-PL')} · ${plan.elapsed_ms} ms`],
  ]
  return (
    <dl className="metrics">
      {rows.map(([label, value]) => (
        <div key={label} className="metric">
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
