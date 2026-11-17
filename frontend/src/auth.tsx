import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, ApiError, setUnauthorizedHandler, type Me, type Membership } from './api'

interface AuthValue {
  user: Me | null
  checking: boolean
  /** Bieżący warsztat (członkostwo) wybrany w nagłówku. */
  workshop: Membership | null
  selectWorkshop: (workshopId: number) => void
  /** Rola w podanym warsztacie (np. warsztacie projektu otwartego z linku). */
  roleIn: (workshopId: number) => Membership['role'] | null
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)
const WORKSHOP_KEY = 'offcut.workshop'

function readSavedWorkshop(): number | null {
  try {
    return Number(localStorage.getItem(WORKSHOP_KEY)) || null
  } catch {
    return null
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null)
  const [checking, setChecking] = useState(true)
  const [workshopId, setWorkshopId] = useState<number | null>(readSavedWorkshop)

  // Przy starcie sprawdzamy sesję (cookie HttpOnly) – 401 oznacza ekran logowania.
  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch((err) => {
        if (!(err instanceof ApiError && err.status === 401)) console.error(err)
      })
      .finally(() => setChecking(false))
    // Każde 401 z API (np. wygasła sesja) wylogowuje użytkownika w interfejsie.
    setUnauthorizedHandler(() => setUser(null))
  }, [])

  const selectWorkshop = useCallback((id: number) => {
    setWorkshopId(id)
    try {
      localStorage.setItem(WORKSHOP_KEY, String(id))
    } catch {
      /* brak dostępu do localStorage – wybór działa do odświeżenia strony */
    }
  }, [])

  const memberships = user?.memberships ?? []
  const workshop = memberships.find((m) => m.workshop_id === workshopId) ?? memberships[0] ?? null

  const value: AuthValue = {
    user,
    checking,
    workshop,
    selectWorkshop,
    roleIn: (id) => memberships.find((m) => m.workshop_id === id)?.role ?? null,
    login: async (email, password) => {
      const res = await api.login(email, password)
      setUser(res.user)
    },
    logout: async () => {
      try {
        await api.logout()
      } finally {
        setUser(null)
      }
    },
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth musi być użyte wewnątrz <AuthProvider>')
  return value
}
