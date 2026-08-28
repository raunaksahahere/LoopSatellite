import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from './api'

export interface AsyncState<T> {
  data: T | null
  loading: boolean
  error: ApiError | null
  reload: () => void
}

/**
 * Minimal fetch-on-mount hook. Loading and error are first-class so every screen
 * can render a real state instead of a blank panel.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | null>(null)
  const [nonce, setNonce] = useState(0)
  const latest = useRef(0)

  useEffect(() => {
    const ticket = ++latest.current
    setLoading(true)
    setError(null)
    fn()
      .then((result) => {
        if (ticket === latest.current) setData(result)
      })
      .catch((err: unknown) => {
        if (ticket !== latest.current) return
        setError(
          err instanceof ApiError ? err : new ApiError(String(err), 0),
        )
      })
      .finally(() => {
        if (ticket === latest.current) setLoading(false)
      })
    // fn is intentionally excluded: callers pass an inline closure.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { data, loading, error, reload }
}

/** For actions the officer triggers — evidence lookup, notice drafting, verify. */
export function useAction<A extends unknown[], T>(fn: (...args: A) => Promise<T>) {
  const [data, setData] = useState<T | null>(null)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  const run = useCallback(
    async (...args: A) => {
      setPending(true)
      setError(null)
      try {
        const result = await fn(...args)
        setData(result)
        return result
      } catch (err) {
        setError(err instanceof ApiError ? err : new ApiError(String(err), 0))
        return null
      } finally {
        setPending(false)
      }
    },
    [fn],
  )

  return { data, pending, error, run, reset: () => setData(null) }
}
