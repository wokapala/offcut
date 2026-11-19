import type { Plan, PlanBar } from '../api'
import { mm } from '../labels'

// Instrukcja cięcia dla warsztatu – krok po kroku, z pozycją znacznika od początku odcinka.
// Liczby pochodzą wyłącznie z planu (te same, co w schemacie i w bilansie backendu).
// Rzaz jest zawsze po stronie dalszej części odcinka, więc element ma pełną zamówioną długość.

function barSteps(bar: PlanBar, kerfMm: number): string[] {
  const steps: string[] = []
  let position = 0
  // Cięcie oddzielające pozostałość = cały rzaz odcinka minus cięcia między elementami (może być 0).
  const finalKerf = bar.kerf_loss_mm - kerfMm * (bar.pieces.length - 1)
  bar.pieces.forEach((piece, i) => {
    position += piece.length_mm // pozycja linii cięcia od początku odcinka
    const name = `element ${mm(piece.length_mm)}${piece.label ? ` (${piece.label})` : ''}`
    const isLast = i === bar.pieces.length - 1
    if (isLast && finalKerf === 0) {
      steps.push(`Ostatni ${name} kończy się na końcu odcinka – bez cięcia`)
    } else {
      steps.push(`Tnij na ${mm(position)} → ${name}`)
    }
    position += kerfMm
  })
  return steps
}

function remainderText(bar: PlanBar): string {
  if (bar.remainder_mm === 0) return 'Pozostałość: brak.'
  return bar.usable_remnant
    ? `Pozostałość ${mm(bar.remainder_mm)} → odłóż do magazynu jako resztkę.`
    : `Pozostałość ${mm(bar.remainder_mm)} → odpad (poniżej progu).`
}

export default function CutInstructions({ plan }: { plan: Plan }) {
  return (
    <div className="instructions" data-testid="cut-instructions">
      <p className="muted small">
        Odmierzaj od początku odcinka. Rzaz {mm(plan.kerf_mm)} jest liczony po stronie dalszej części odcinka – każdy
        odcięty element ma pełną długość.
      </p>
      {plan.bars.map((bar, index) => (
        <section key={bar.stock_item_id} className="instruction-bar">
          <h3>
            {index + 1}. Odcinek #{bar.stock_item_id} · {mm(bar.stock_length_mm)} · {bar.stock_is_remnant ? 'resztka' : 'nowy'} ·{' '}
            {bar.spec_label}
            {bar.stock_label && <span className="muted"> · {bar.stock_label}</span>}
          </h3>
          <ol>
            {barSteps(bar, plan.kerf_mm).map((step, i) => (
              <li key={i}>
                <span className="checkbox" aria-hidden="true" /> {step}
              </li>
            ))}
          </ol>
          <p className={bar.usable_remnant ? 'remnant-note' : 'muted'}>{remainderText(bar)}</p>
        </section>
      ))}
    </div>
  )
}
