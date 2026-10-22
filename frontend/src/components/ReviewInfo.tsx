import type { ReviewFields } from '../api'

/** "Content pending expert review" tag + citation list, for any exercise, program, or article. */
export default function ReviewInfo({ item }: { item: Pick<ReviewFields, 'review_notice' | 'citations'> }) {
  return (
    <div className="review-info">
      {item.review_notice ? (
        <span className="review-tag">{item.review_notice}</span>
      ) : (
        <span className="review-tag review-tag-ok">Reviewed by a professional</span>
      )}
      <div className="citations">
        <strong>Citations:</strong>{' '}
        {item.citations.length === 0 ? (
          <em>None yet</em>
        ) : (
          <ul>
            {item.citations.map((c) => (
              <li key={c.claim + c.source}>
                {c.claim}: {c.source}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
