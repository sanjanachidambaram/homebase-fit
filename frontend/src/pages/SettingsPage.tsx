import { useEffect, useState } from 'react'
import { deleteAccount, fetchAccount, type Account } from '../api'
import AccountForm from '../components/AccountForm'
import { PrivacyNote } from '../components/Legal'
import Link from '../components/Link'
import { setSession, useSession } from '../session'

export default function SettingsPage() {
  const session = useSession()
  const [account, setAccount] = useState<Account | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deletedSummary, setDeletedSummary] = useState<Record<string, number> | null>(null)

  useEffect(() => {
    if (!session) return
    let cancelled = false
    fetchAccount(session.userId, session.token)
      .then((a) => !cancelled && setAccount(a))
      .catch((e: Error) => {
        if (cancelled) return
        setError(e.message)
        setSession(null) // stale or deleted account
      })
    return () => {
      cancelled = true
    }
  }, [session])

  async function deleteEverything() {
    if (!session) return
    setDeleting(true)
    setError(null)
    try {
      const result = await deleteAccount(session.userId, session.token)
      setDeletedSummary(result.rows_removed)
      setAccount(null)
      setConfirming(false)
      setSession(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDeleting(false)
    }
  }

  if (deletedSummary) {
    return (
      <>
        <h2 className="page-title">Settings</h2>
        <p className="success">Your account and all of your data have been permanently deleted.</p>
        <p className="meta">
          Removed: {Object.entries(deletedSummary).map(([table, n]) => `${n} ${table.replace(/_/g, ' ')}`).join(', ')}.
        </p>
      </>
    )
  }

  if (!session) {
    return (
      <>
        <h2 className="page-title">Settings</h2>
        {error && <p className="error">{error}</p>}
        <p>Sign in to see or delete your data.</p>
        <AccountForm initialMode="login" />
      </>
    )
  }

  const profile = account?.quiz_profile

  return (
    <>
      <h2 className="page-title">Settings</h2>
      {error && <p className="error">{error}</p>}

      <section className="settings-section">
        <h3>Your account</h3>
        <p>
          <strong>Email:</strong> {session.email}
        </p>
        {account && (
          <p>
            <strong>Member since:</strong> {new Date(account.created_at).toLocaleDateString()}
          </p>
        )}
        {profile ? (
          <p>
            <strong>Quiz:</strong> completed. Medical disclaimer accepted{' '}
            {new Date(profile.consent_accepted_at).toLocaleString()}.
          </p>
        ) : (
          <p>
            <strong>Quiz:</strong> not taken yet. <Link to="/quiz">Take the quiz</Link>
          </p>
        )}
        <button className="btn-secondary" onClick={() => setSession(null)}>
          Sign out
        </button>
      </section>

      <PrivacyNote />

      <section className="settings-section danger-zone">
        <h3>Delete my data</h3>
        <p>
          Permanently deletes your account, quiz answers, favorite exercises, workout logs, measurements, and safety notices. This can't be
          undone.
        </p>
        {!confirming ? (
          <button className="btn-danger" onClick={() => setConfirming(true)}>
            Delete my data
          </button>
        ) : (
          <div className="confirm-box" role="alertdialog" aria-label="Confirm deletion">
            <p>
              <strong>Are you sure?</strong> Everything stored for {session.email} will be deleted right away.
            </p>
            <div className="button-row">
              <button className="btn-secondary" onClick={() => setConfirming(false)} disabled={deleting}>
                Cancel
              </button>
              <button className="btn-danger" onClick={deleteEverything} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Yes, permanently delete everything'}
              </button>
            </div>
          </div>
        )}
      </section>
    </>
  )
}
