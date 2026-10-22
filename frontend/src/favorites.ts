// The signed-in user's favorited ("faved") exercises, shared by the cards, the My Faves tab, and the detail view.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { addFavorite, fetchFavorites, removeFavorite, type Exercise } from './api'
import { setSession, useSession } from './session'

export interface Favorites {
  signedIn: boolean
  /** Full exercises, newest fave first. Empty when signed out. */
  favorites: Exercise[]
  loaded: boolean
  isFavorite: (id: string) => boolean
  isPending: (id: string) => boolean
  /** Faves or un-faves. When signed out it sets `needsSignIn` instead. */
  toggle: (exercise: Exercise) => Promise<void>
  needsSignIn: boolean
  error: string | null
}

export function useFavorites(): Favorites {
  const session = useSession()
  const token = session?.token
  const [loadedFor, setLoadedFor] = useState<{ token: string; list: Exercise[] } | null>(null)
  const [pending, setPending] = useState<ReadonlySet<string>>(new Set())
  const [needsSignIn, setNeedsSignIn] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    fetchFavorites(token)
      .then((list) => !cancelled && setLoadedFor({ token, list }))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [token])

  // Only trust the loaded list if it belongs to the current sign-in.
  const favorites = useMemo(() => (token && loadedFor?.token === token ? loadedFor.list : []), [token, loadedFor])
  const ids = useMemo(() => new Set(favorites.map((f) => f.id)), [favorites])

  const toggle = useCallback(
    async (exercise: Exercise) => {
      if (!token) {
        setNeedsSignIn(true)
        return
      }
      if (pending.has(exercise.id)) return
      setError(null)
      setPending((p) => new Set(p).add(exercise.id))
      try {
        const wasFavorite = ids.has(exercise.id)
        if (wasFavorite) await removeFavorite(exercise.id, token)
        else await addFavorite(exercise.id, token)
        setLoadedFor((cur) =>
          cur && cur.token === token
            ? { token, list: wasFavorite ? cur.list.filter((f) => f.id !== exercise.id) : [exercise, ...cur.list] }
            : cur,
        )
      } catch (e) {
        const message = (e as Error).message
        if (/sign in/i.test(message)) setSession(null) // stale token or deleted account
        setError(message)
      } finally {
        setPending((p) => {
          const next = new Set(p)
          next.delete(exercise.id)
          return next
        })
      }
    },
    [token, pending, ids],
  )

  return {
    signedIn: !!token,
    favorites,
    loaded: !!token && loadedFor?.token === token,
    isFavorite: (id) => ids.has(id),
    isPending: (id) => pending.has(id),
    toggle,
    needsSignIn: needsSignIn && !token,
    error,
  }
}
