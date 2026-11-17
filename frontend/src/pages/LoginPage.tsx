import { useState, type FormEvent } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { ErrorAlert } from '../components/ui'
import { useAction } from '../hooks'

const DEMO_ACCOUNTS = [
  { email: 'wlasciciel@offcut.demo', who: 'właściciel, „Warsztat Demo”' },
  { email: 'operator@offcut.demo', who: 'operator, „Warsztat Demo”' },
  { email: 'obcy@offcut.demo', who: 'właściciel innego warsztatu' },
]
const DEMO_PASSWORD = 'Demo1234!'

export default function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const action = useAction()
  const from = (location.state as { from?: string } | null)?.from ?? '/projects'

  if (user) return <Navigate to={from} replace />

  function submit(e: FormEvent) {
    e.preventDefault()
    action.run(async () => {
      await login(email, password)
      navigate(from, { replace: true })
    })
  }

  return (
    <div className="login-wrap">
      <div className="login-card card">
        <div className="wordmark wordmark-lg">
          <span className="wordmark-mark" aria-hidden="true" />
          Offcut
        </div>
        <p className="muted">Optymalizacja cięcia materiałów i wykorzystania resztek</p>

        <form onSubmit={submit} className="form-stack">
          <label>
            E-mail
            <input
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              data-testid="login-email"
            />
          </label>
          <label>
            Hasło
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              data-testid="login-password"
            />
          </label>
          <ErrorAlert error={action.error} />
          <button type="submit" className="btn btn-primary" disabled={action.pending} data-testid="login-submit">
            {action.pending ? 'Logowanie…' : 'Zaloguj się'}
          </button>
        </form>

        <aside className="demo-box">
          <strong>Lokalne konta demonstracyjne</strong>
          <p className="muted small">Tylko dla lokalnej wersji demo. Hasło: <code>{DEMO_PASSWORD}</code></p>
          <ul>
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.email}>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => {
                    setEmail(a.email)
                    setPassword(DEMO_PASSWORD)
                  }}
                >
                  {a.email}
                </button>{' '}
                <span className="muted small">– {a.who}</span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  )
}
