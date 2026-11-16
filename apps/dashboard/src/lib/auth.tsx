import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, tokenStore } from '@/lib/api'
import type { TokenResponse, User } from '@/lib/types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  register: (name: string, email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState<boolean>(() => tokenStore.get() !== null)

  // Restore the session on refresh.
  useEffect(() => {
    if (!tokenStore.get()) return
    api<User>('/auth/me')
      .then(setUser)
      .catch(() => tokenStore.clear())
      .finally(() => setLoading(false))
  }, [])

  // Any 401 from the API drops the session.
  useEffect(() => {
    const onUnauthorized = () => setUser(null)
    window.addEventListener('rl-unauthorized', onUnauthorized)
    return () => window.removeEventListener('rl-unauthorized', onUnauthorized)
  }, [])

  const accept = useCallback((res: TokenResponse) => {
    tokenStore.set(res.access_token)
    setUser(res.user)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      login: async (email, password) => accept(await api<TokenResponse>('/auth/login', { method: 'POST', body: { email, password } })),
      register: async (name, email, password) =>
        accept(await api<TokenResponse>('/auth/register', { method: 'POST', body: { name, email, password } })),
      logout: () => {
        tokenStore.clear()
        setUser(null)
      },
    }),
    [user, loading, accept],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
