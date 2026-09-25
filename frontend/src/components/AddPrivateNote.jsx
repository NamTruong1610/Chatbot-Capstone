import { useState } from 'react'
import { ingestPrivateNote } from '../api.js'

// Staff-only: paste an internal note that becomes private, staff-retrievable content for the
// selected business. Rendered by App only when role === 'staff' (demo gating); the write itself is
// admin-token-guarded on the backend. Synchronous — no crawl, so no polling.
export default function AddPrivateNote({ domainId, adminToken, onAdminToken }) {
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [result, setResult] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setResult('')
    setBusy(true)
    try {
      const res = await ingestPrivateNote({ domainId, title, text, adminToken })
      setResult(`Added “${res.title}” as private (${res.chunks_added} chunk(s)). Ask about it as staff.`)
      setTitle('')
      setText('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="add-note">
      <summary>Add internal note (staff)</summary>
      <form onSubmit={submit}>
        <p className="note-target">
          Private content for <code>{domainId || '— select a business —'}</code>
        </p>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="note title (e.g. Escalation contacts)"
          required
        />
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="internal note text — staff-only"
          rows={4}
          required
        />
        <input
          type="password"
          value={adminToken}
          onChange={(e) => onAdminToken(e.target.value)}
          placeholder="admin token (X-API-Key)"
          required
        />
        <button type="submit" disabled={busy || !domainId || !title || !text || !adminToken}>
          {busy ? 'Adding…' : 'Add private note'}
        </button>
        {result && <p className="add-status">{result}</p>}
        {error && <p className="add-error">⚠ {error}</p>}
      </form>
    </details>
  )
}
