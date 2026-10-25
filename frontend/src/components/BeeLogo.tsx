// The Bee Fit logo: a little bee lifting a dumbbell over its head, drawn in SVG (no image file). The same drawing is
// public/favicon.svg. Colors are fixed hex values matching the tokens in index.css, so it looks the same everywhere.
// Decorative by default (aria-hidden); pass a title when the logo stands alone and needs a name.

export const BEE_COLORS = {
  body: '#ffc61a', // --yellow
  ink: '#2b2a1e', // --ink
  plate: '#b34a00', // --orange-deep
  wing: '#ffffff',
  wingLine: '#7a5700', // --honey-deep
  cheek: '#ff8c1a', // --orange
}

export default function BeeLogo({ size = 32, title, className }: { size?: number; title?: string; className?: string }) {
  const c = BEE_COLORS
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      focusable="false"
    >
      {/* wings, behind everything */}
      <ellipse cx="18" cy="40" rx="9" ry="6.5" transform="rotate(-25 18 40)" fill={c.wing} stroke={c.wingLine} strokeWidth="2" />
      <ellipse cx="46" cy="40" rx="9" ry="6.5" transform="rotate(25 46 40)" fill={c.wing} stroke={c.wingLine} strokeWidth="2" />
      {/* arms up to the bar */}
      <path d="M25 37 L19 10 M39 37 L45 10" stroke={c.ink} strokeWidth="3.2" strokeLinecap="round" fill="none" />
      {/* striped body and stinger */}
      <path d="M32 61 L29.5 57 L34.5 57 Z" fill={c.ink} />
      <ellipse cx="32" cy="46" rx="12" ry="12.5" fill={c.body} stroke={c.ink} strokeWidth="2.5" />
      <path d="M20.6 43 H43.4 M21.4 50.5 H42.6" stroke={c.ink} strokeWidth="4" />
      {/* head */}
      <circle cx="32" cy="27" r="9.5" fill={c.body} stroke={c.ink} strokeWidth="2.5" />
      <path d="M28.5 18.5 L26 13.5 M35.5 18.5 L38 13.5" stroke={c.ink} strokeWidth="2" strokeLinecap="round" />
      <circle cx="26" cy="13.2" r="1.8" fill={c.ink} />
      <circle cx="38" cy="13.2" r="1.8" fill={c.ink} />
      <circle cx="28.6" cy="26" r="1.7" fill={c.ink} />
      <circle cx="35.4" cy="26" r="1.7" fill={c.ink} />
      <circle cx="26.4" cy="29.6" r="1.6" fill={c.cheek} opacity="0.7" />
      <circle cx="37.6" cy="29.6" r="1.6" fill={c.cheek} opacity="0.7" />
      <path d="M29.5 30.4 Q32 33 34.5 30.4" stroke={c.ink} strokeWidth="1.6" strokeLinecap="round" fill="none" />
      {/* the dumbbell */}
      <rect x="8" y="7.5" width="48" height="4" rx="2" fill={c.ink} />
      <rect x="3" y="2.5" width="7" height="14" rx="2.5" fill={c.plate} stroke={c.ink} strokeWidth="1.5" />
      <rect x="54" y="2.5" width="7" height="14" rx="2.5" fill={c.plate} stroke={c.ink} strokeWidth="1.5" />
    </svg>
  )
}
