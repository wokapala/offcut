import type { Plan, PlanBar } from '../api'
import { mm } from '../labels'

// Schemat rozkroju budowany WYŁĄCZNIE z liczb zwróconych przez API (model rzazu jest w backendzie).
// Dla każdego odcinka: elementy w kolejności, rzaz między nimi, cięcie końcowe, pozostałość.

const PALETTE = ['#4c78a8', '#d08c3c', '#8e6bbf', '#3f97b5', '#b5657d', '#7f8c3a']

type SegmentKind = 'piece' | 'kerf' | 'remnant' | 'scrap'
interface Segment {
  kind: SegmentKind
  mm: number
  title: string
  text?: string
  color?: string
}

function barSegments(bar: PlanBar, kerfMm: number, colorOf: (id: number | null) => string): Segment[] {
  const segments: Segment[] = []
  bar.pieces.forEach((piece, i) => {
    if (i > 0 && kerfMm > 0) segments.push({ kind: 'kerf', mm: kerfMm, title: `Rzaz ${kerfMm} mm` })
    segments.push({
      kind: 'piece',
      mm: piece.length_mm,
      text: String(piece.length_mm),
      title: `Element ${piece.length_mm} mm${piece.label ? ` – ${piece.label}` : ''}`,
      color: colorOf(piece.demand_item_id),
    })
  })
  // Cięcie oddzielające pozostałość = cały rzaz odcinka minus cięcia między elementami (może być 0).
  const finalKerf = bar.kerf_loss_mm - kerfMm * (bar.pieces.length - 1)
  if (finalKerf > 0) segments.push({ kind: 'kerf', mm: finalKerf, title: `Cięcie końcowe ${finalKerf} mm` })
  if (bar.remainder_mm > 0) {
    const usable = bar.usable_remnant
    const text = `${usable ? 'Resztka' : 'Odpad'} ${bar.remainder_mm} mm`
    segments.push({ kind: usable ? 'remnant' : 'scrap', mm: bar.remainder_mm, text, title: text })
  }

  if (import.meta.env.DEV) {
    const sum = segments.reduce((acc, s) => acc + s.mm, 0)
    if (sum !== bar.stock_length_mm) {
      console.warn(`CutDiagram: odcinek #${bar.stock_item_id} – suma segmentów ${sum} ≠ ${bar.stock_length_mm} mm`)
    }
  }
  return segments
}

export default function CutDiagram({ plan }: { plan: Plan }) {
  // Kolor elementu zależy od pozycji zapotrzebowania – ten sam w obu planach projektu.
  const demandIds = [...new Set(plan.bars.flatMap((b) => b.pieces.map((p) => p.demand_item_id)))].sort(
    (a, b) => (a ?? 0) - (b ?? 0),
  )
  const colorOf = (id: number | null) => PALETTE[demandIds.indexOf(id) % PALETTE.length]
  const longest = Math.max(...plan.bars.map((b) => b.stock_length_mm), 1)

  const pieceLegend = demandIds.map((id) => {
    const piece = plan.bars.flatMap((b) => b.pieces).find((p) => p.demand_item_id === id)!
    return { id, color: colorOf(id), text: `${piece.length_mm} mm${piece.label ? ` · ${piece.label}` : ''}` }
  })

  if (plan.bars.length === 0) return <p className="muted">Plan nie zawiera odcinków.</p>

  return (
    <div className="diagram" data-testid={`diagram-${plan.method}`}>
      <div className="legend">
        {pieceLegend.map((l) => (
          <span key={l.id ?? 'none'} className="legend-item">
            <i style={{ background: l.color }} /> {l.text}
          </span>
        ))}
        <span className="legend-item">
          <i className="seg-kerf" /> rzaz ({plan.kerf_mm} mm)
        </span>
        <span className="legend-item">
          <i className="seg-remnant" /> użyteczna resztka (≥ {plan.min_remnant_mm} mm)
        </span>
        <span className="legend-item">
          <i className="seg-scrap" /> odpad
        </span>
      </div>

      {plan.bars.map((bar) => (
        <div key={bar.stock_item_id} className="bar-block">
          <div className="bar-caption">
            <strong>Odcinek #{bar.stock_item_id}</strong> · {mm(bar.stock_length_mm)} ·{' '}
            {bar.stock_is_remnant ? 'Resztka' : 'Nowy'} · {bar.spec_label}
            {bar.stock_label && <span className="muted"> · {bar.stock_label}</span>}
          </div>
          <div className="bar" style={{ width: `${(bar.stock_length_mm / longest) * 100}%` }}>
            {barSegments(bar, plan.kerf_mm, colorOf).map((s, i) => (
              <div
                key={i}
                className={`seg seg-${s.kind}`}
                style={{ flexGrow: s.mm, background: s.color }}
                title={s.title}
              >
                {/* Napis tylko w segmentach dość szerokich (≥ 7% odcinka); wąskie mają podpowiedź i podsumowanie. */}
                {s.text && s.mm / bar.stock_length_mm >= 0.07 && <span>{s.text}</span>}
              </div>
            ))}
          </div>
          <div className="bar-summary">
            cięcia: {bar.cut_count} · rzaz: {mm(bar.kerf_loss_mm)} · pozostałość: {mm(bar.remainder_mm)}
            {bar.remainder_mm > 0 && (bar.usable_remnant ? ' (użyteczna resztka)' : ' (odpad)')}
          </div>
        </div>
      ))}
    </div>
  )
}
