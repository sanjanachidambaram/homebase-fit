/** Three bouncing dots plus a line of text (the dots stay still for reduced motion). */
export default function Loading({ text }: { text: string }) {
  return (
    <p className="loading" role="status">
      <span className="dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      {text}
    </p>
  )
}
