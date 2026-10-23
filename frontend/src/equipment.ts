// The live equipment list, fetched once and shared by Build Your Own and the library filter.
import { useEffect, useState } from 'react'
import { fetchEquipment, type EquipmentOption } from './api'

let cached: Promise<EquipmentOption[]> | null = null

/** null while loading; [] if it couldn't load (the pickers then show a short message). */
export function useEquipmentOptions(): EquipmentOption[] | null {
  const [options, setOptions] = useState<EquipmentOption[] | null>(null)
  useEffect(() => {
    let cancelled = false
    cached ??= fetchEquipment().catch(() => {
      cached = null // try again next time
      return []
    })
    cached.then((o) => !cancelled && setOptions(o))
    return () => {
      cancelled = true
    }
  }, [])
  return options
}

/** For tests: forget the cached list. */
export function resetEquipmentCache() {
  cached = null
}
