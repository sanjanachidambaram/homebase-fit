import BeeLogo from '../BeeLogo'

/** The Bee Fit bee lifting its dumbbell, three bouncing dots, and a line of text (all still for reduced motion). */
export default function Loading({ text }: { text: string }) {
  return (
    <p className="loading" role="status">
      <BeeLogo size={30} className="loading-bee" />
      <span className="dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      {text}
    </p>
  )
}
