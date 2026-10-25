// "Workout Basics": the Workout Basics articles (GET /api/basics, from content/basics/*.md) and Ask Workout Basics.
// Split out of the old "Your Plan & Basics" page on 2026-10-23, so the plan and the articles each have their own page.
import { useEffect, useState, type ReactNode } from 'react'
import { fetchArticles, type Article } from '../api'
import AskBasics from '../components/dashboard/AskBasics'
import Link from '../components/Link'
import ReviewInfo from '../components/ReviewInfo'
import { useSession } from '../session'

/** **bold** inside a line, as React nodes (never HTML). */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? <strong key={i}>{part.slice(2, -2)}</strong> : part,
  )
}

/** The small subset of Markdown the articles use: ## headings, - bullets, > notes, and paragraphs. */
function ArticleBody({ markdown }: { markdown: string }) {
  const blocks = markdown.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean)
  return (
    <>
      {blocks.map((b, i) => {
        if (b.startsWith('## ')) return <h5 key={i}>{b.slice(3)}</h5>
        if (b.startsWith('> ')) return <p key={i} className="pending-note">{inline(b.replace(/^>\s?/gm, ''))}</p>
        if (b.startsWith('- ')) {
          return (
            <ul key={i}>
              {b.split('\n').map((li, j) => (
                <li key={j}>{inline(li.replace(/^-\s+/, ''))}</li>
              ))}
            </ul>
          )
        }
        return <p key={i}>{inline(b.replace(/\n/g, ' '))}</p>
      })}
    </>
  )
}

export default function BasicsPage() {
  const session = useSession()
  const [articles, setArticles] = useState<Article[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchArticles()
      .then(setArticles)
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <>
      <h2 className="page-title">Workout Basics</h2>
      <p className="page-sub">Short, plain-language guides. They're placeholder drafts until a professional reviews them.</p>

      {session ? (
        <AskBasics token={session.token} />
      ) : (
        <p className="notice">
          <Link to="/">Sign in</Link> to ask a question about these guides.
        </p>
      )}

      <h3 className="section-title">The guides</h3>
      {error && <p className="error">Couldn't load the guides: {error}</p>}
      <div className="content-list">
        {articles.map((a) => (
          <article key={a.slug} className="content-item">
            <h4>{a.title}</h4>
            <p className="meta">Category: {a.category.replace(/_/g, ' ')}</p>
            <ReviewInfo item={a} />
            <details className="article-body">
              <summary>Read it</summary>
              <ArticleBody markdown={a.content} />
            </details>
          </article>
        ))}
      </div>
    </>
  )
}
