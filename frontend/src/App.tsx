import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth'
import Layout from './components/Layout'
import { Empty, Spinner } from './components/ui'
import LoginPage from './pages/LoginPage'
import PlanPage from './pages/PlanPage'
import ProjectPage from './pages/ProjectPage'
import ProjectsPage from './pages/ProjectsPage'
import StockPage from './pages/StockPage'

/** Chronione widoki: bez sesji przekierowanie na /login (z zapamiętaniem adresu). */
function RequireAuth() {
  const { user, checking } = useAuth()
  const location = useLocation()
  if (checking) return <Spinner label="Sprawdzanie sesji…" />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <Layout />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="/stock" element={<StockPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:id" element={<ProjectPage />} />
        <Route path="/plans/:id" element={<PlanPage />} />
        <Route path="*" element={<Empty>Nie ma takiej strony.</Empty>} />
      </Route>
    </Routes>
  )
}
