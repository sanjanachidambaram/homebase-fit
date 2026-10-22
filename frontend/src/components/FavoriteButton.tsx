import { useState, type CSSProperties } from 'react'

// Directions for the little hearts that float out when you fave something (design.md 5).
const BURST = [
  [-22, -20], [0, -28], [22, -20], [-26, 4], [26, 4], [0, 18],
]

/** Heart toggle for faving an exercise. */
export default function FavoriteButton({
  name,
  favorited,
  pending,
  onToggle,
  withLabel = false,
}: {
  name: string
  favorited: boolean
  pending: boolean
  onToggle: () => void
  /** show "Add to faves" / "Saved to faves" text next to the heart (used in the detail view) */
  withLabel?: boolean
}) {
  const [pop, setPop] = useState(0)   // bumps on each fave, to replay the animation
  return (
    <button
      type="button"
      className={`heart${favorited ? ' heart-on' : ''}${withLabel ? ' heart-labeled' : ''}${pop ? ' heart-pop' : ''}`}
      aria-pressed={favorited}
      aria-label={favorited ? `Remove ${name} from faves` : `Add ${name} to faves`}
      disabled={pending}
      onClick={(e) => {
        e.stopPropagation()
        if (!favorited) setPop((n) => n + 1)
        onToggle()
      }}
      onAnimationEnd={(e) => e.animationName === 'heart-pop' && setPop(0)}
    >
      {pop > 0 && (
        <span key={pop} className="heart-burst" aria-hidden="true">
          {BURST.map(([dx, dy]) => (
            <span key={`${dx},${dy}`} style={{ '--dx': `${dx}px`, '--dy': `${dy}px` } as CSSProperties}>
              ♥
            </span>
          ))}
        </span>
      )}
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" focusable="false">
        <path
          d="M12 21s-7.5-4.6-9.6-9.3C.9 8.2 2.7 4.5 6.2 4.5c2 0 3.3 1 3.8 2 .5-1 1.8-2 3.8-2 3.5 0 5.3 3.7 3.8 7.2C19.5 16.4 12 21 12 21z"
          fill={favorited ? 'currentColor' : 'none'}
          stroke="currentColor"
          strokeWidth="2"
          strokeLinejoin="round"
        />
      </svg>
      {withLabel && <span>{favorited ? 'Saved to faves' : 'Add to faves'}</span>}
    </button>
  )
}
