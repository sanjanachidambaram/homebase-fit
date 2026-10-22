import type { MediaType } from '../api'

/** Renders an exercise's demo according to its media_type, so a video can replace an image with no other change. */
export default function DemoMedia({
  url,
  type,
  alt,
  compact = false,
}: {
  url: string | null
  type: MediaType | null
  alt: string
  /** compact = thumbnail in a card (videos show a still frame, no controls) */
  compact?: boolean
}) {
  if (!url || !type) return <div className="no-media">No demo yet</div>
  if (type === 'video') {
    return compact ? (
      <video src={url} muted playsInline preload="metadata" aria-label={alt} />
    ) : (
      <video src={url} controls muted loop playsInline preload="metadata" aria-label={alt} />
    )
  }
  return <img src={url} alt={alt} loading={compact ? 'lazy' : undefined} />
}
