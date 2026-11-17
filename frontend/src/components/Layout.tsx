import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../auth'
import { roleLabel } from '../labels'
import { Badge } from './ui'

export default function Layout() {
  const { user, workshop, selectWorkshop, logout } = useAuth()
  if (!user) return null

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <NavLink to="/projects" className="wordmark">
            <span className="wordmark-mark" aria-hidden="true" />
            Offcut
          </NavLink>
          <nav className="nav">
            <NavLink to="/stock" data-testid="nav-stock">
              Magazyn
            </NavLink>
            <NavLink to="/projects" data-testid="nav-projects">
              Projekty
            </NavLink>
          </nav>
          <div className="topbar-user">
            {user.memberships.length > 1 ? (
              <select
                aria-label="Warsztat"
                data-testid="workshop-select"
                value={workshop?.workshop_id}
                onChange={(e) => selectWorkshop(Number(e.target.value))}
              >
                {user.memberships.map((m) => (
                  <option key={m.workshop_id} value={m.workshop_id}>
                    {m.workshop_name}
                  </option>
                ))}
              </select>
            ) : (
              <span className="workshop-name">{workshop?.workshop_name}</span>
            )}
            <span className="user-name">{user.full_name}</span>
            {workshop && (
              <Badge tone={workshop.role === 'OWNER' ? 'accent' : 'neutral'} testId="role-badge">
                {roleLabel[workshop.role]}
              </Badge>
            )}
            <button type="button" className="btn btn-ghost btn-sm" onClick={logout} data-testid="logout">
              Wyloguj
            </button>
          </div>
        </div>
      </header>
      <main className="page">
        {workshop ? <Outlet /> : <p className="empty">Twoje konto nie należy do żadnego warsztatu.</p>}
      </main>
    </>
  )
}
