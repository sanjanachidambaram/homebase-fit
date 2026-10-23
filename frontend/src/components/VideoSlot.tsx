// A video that may not exist yet: plays it if one of the files is there, otherwise shows a "coming soon" placeholder
// (never a broken player). Some hosts answer a missing file with the app's index.html, so a file only counts if it's
// served as video.
import { useEffect, useState } from 'react'

export default function VideoSlot({ sources, label }: { sources: string[]; label: string }) {
  const [src, setSrc] = useState<string | null | undefined>(undefined) // undefined = still checking
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      for (const s of sources) {
        try {
          const r = await fetch(s, { method: 'HEAD' })
          if (r.ok && (r.headers.get('content-type') ?? '').startsWith('video/')) {
            if (!cancelled) setSrc(s)
            return
          }
        } catch {
          // try the next one
        }
      }
      if (!cancelled) setSrc(null)
    })()
    return () => {
      cancelled = true
    }
  }, [sources])

  if (src) {
    return (
      <video className="video-slot" src={src} controls playsInline preload="metadata">
        {label}
      </video>
    )
  }
  return (
    <div className="video-slot video-placeholder" role="img" aria-label={`${label}: coming soon`}>
      <span aria-hidden="true">▶</span>
      <p>{src === undefined ? 'Loading the video…' : `${label}: coming soon`}</p>
    </div>
  )
}
