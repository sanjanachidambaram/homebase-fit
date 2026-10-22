// Programs and Fitness Basics articles with their review status and citations.
import { useEffect, useState } from 'react'
import { fetchArticles, fetchPrograms, type Article, type Program, type ReviewFields } from '../api'

function ReviewInfo({ item }: { item: ReviewFields }) {
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

export default function ContentPage() {
  const [programs, setPrograms] = useState<Program[]>([])
  const [articles, setArticles] = useState<Article[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([fetchPrograms(), fetchArticles()])
      .then(([p, a]) => {
        setPrograms(p)
        setArticles(a)
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <>
      <h2 className="page-title">Programs &amp; Fitness Basics</h2>
      {error && <p className="error">Couldn't load content: {error}</p>}

      <h3 className="section-title">Programs</h3>
      <div className="content-list">
        {programs.map((p) => (
          <article key={p.id} className="content-item">
            <h4>{p.name}</h4>
            <p className="meta">Goals: {p.goal_tags.join(', ').replace(/_/g, ' ')}</p>
            <ReviewInfo item={p} />
            <p>{p.description}</p>
          </article>
        ))}
      </div>

      <h3 className="section-title">Fitness Basics</h3>
      <div className="content-list">
        {articles.map((a) => (
          <article key={a.slug} className="content-item">
            <h4>{a.title}</h4>
            <p className="meta">Category: {a.category.replace(/_/g, ' ')}</p>
            <ReviewInfo item={a} />
          </article>
        ))}
      </div>
    </>
  )
}
