import { useState } from 'react'
import { addBusiness, getBusinessStatus } from '../api.js'

const POLL_INTERVAL_MS = 2000
const MAX_POLLS = 180 // ~6 min ceiling so a stuck crawl doesn't poll forever

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Add a business live: POST /api/crawl/site with the admin token, then poll the status endpoint
// (pending → crawling → ingesting → ready | failed). While polling we refresh the selector so the
// new business appears there with its live status; on ready we select it.
export default function AddBusinessForm({ adminToken, onAdminToken, onDomainsChanged, onReady }) {
  const [domainId, setDomainId] = useState('')
  const [rootUrl, setRootUrl] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [status, setStatus] = useState('') // live ingest status shown to the user
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setStatus('pending')
    setBusy(true)
    try {
      await addBusiness({ domainId, rootUrl, displayName, adminToken })
      let settled = false
      for (let i = 0; i < MAX_POLLS && !settled; i++) {
        await sleep(POLL_INTERVAL_MS)
        const business = await getBusinessStatus(domainId)
        setStatus(business.status)
        await onDomainsChanged() // reflect the live status in the selector dropdown
        if (business.status === 'ready') {
          settled = true
          onReady(domainId) // select the newly-ready business
        } else if (business.status === 'failed') {
          settled = true
          setError(business.error || 'ingest failed')
        }
      }
      if (!settled) setError('timed out waiting for the crawl to finish')
    } catch (err) {
      setError(err.message)
      setStatus('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="add-business">
      <summary>Add a business</summary>
      <form onSubmit={submit}>
        <div className="add-fields">
          <input
            value={domainId}
            onChange={(e) => setDomainId(e.target.value)}
            placeholder="domain_id (e.g. cutpro)"
            required
          />
          <input
            value={rootUrl}
            onChange={(e) => setRootUrl(e.target.value)}
            placeholder="root_url (https://…)"
            required
          />
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="display name (optional)"
          />
          <input
            type="password"
            value={adminToken}
            onChange={(e) => onAdminToken(e.target.value)}
            placeholder="admin token (X-API-Key)"
            required
          />
          <button type="submit" disabled={busy || !domainId || !rootUrl || !adminToken}>
            {busy ? 'Adding…' : 'Add'}
          </button>
        </div>
        {status && !error && (
          <p className="add-status">
            status: <strong>{status}</strong>
            {status === 'ready' ? ' — selectable in the dropdown now.' : ' …'}
          </p>
        )}
        {error && <p className="add-error">⚠ {error}</p>}
      </form>
    </details>
  )
}
