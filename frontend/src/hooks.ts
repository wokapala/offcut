import { useCallback, useEffect, useState } from 'react'

/** Ładuje dane przy montowaniu i przy zmianie `deps`. Zwraca też `reload` i `setData`. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    load()
      .then((value) => !cancelled && setData(value))
      .catch((err) => !cancelled && setError(err))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
    // `load` celowo pomijamy w zależnościach – o ponownym ładowaniu decydują `deps`.
  }, [...deps, version])

  const reload = useCallback(() => setVersion((v) => v + 1), [])
  return { data, setData, error, loading, reload }
}

/** Obsługa akcji (POST/PATCH/DELETE): stan „w toku” i ostatni błąd. */
export function useAction() {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const run = useCallback(async (action: () => Promise<void>) => {
    setPending(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err)
    } finally {
      setPending(false)
    }
  }, [])

  return { pending, error, run, clearError: () => setError(null) }
}
