import { useEffect, useState, type CSSProperties } from 'react'

const COLORS = ['var(--orange)', 'var(--yellow)', 'var(--green)', 'var(--honey)', 'var(--rust)']
const PIECES = 18

/** A quick burst of CSS confetti (~1.6s), then it removes itself. Hidden entirely for reduced motion (see App.css). */
export default function Confetti() {
  const [visible, setVisible] = useState(true)
  useEffect(() => {
    const t = setTimeout(() => setVisible(false), 1800)
    return () => clearTimeout(t)
  }, [])
  if (!visible) return null
  return (
    <div className="confetti" aria-hidden="true">
      {Array.from({ length: PIECES }, (_, i) => (
        <span
          key={i}
          style={
            {
              left: `${(i * 53) % 100}%`,
              background: COLORS[i % COLORS.length],
              animationDelay: `${(i % 6) * 45}ms`,
              '--drift': `${((i * 37) % 60) - 30}px`,
              '--spin': `${(i * 67) % 360}deg`,
            } as CSSProperties
          }
        />
      ))}
    </div>
  )
}
