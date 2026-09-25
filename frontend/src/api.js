// Thin fetch layer over the FastAPI backend. Every call goes to VITE_API_BASE (default the local
// dev backend on :8000); CORS on the backend permits this cross-origin call from the Vite dev server.

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

async function jsonOrThrow(resp) {
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = await resp.json()
      detail = body.detail || detail
    } catch {
      // non-JSON error body — keep the status text
    }
    throw new Error(`${resp.status} — ${detail}`)
  }
  return resp.json()
}

export async function getDomains() {
  return jsonOrThrow(await fetch(`${API_BASE}/api/domains`))
}

export async function sendMessage({ message, domainId, role, sessionId }) {
  return jsonOrThrow(
    await fetch(`${API_BASE}/api/chat/message`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // session_id is minted by the client and reused across a conversation so multi-turn
      // follow-ups work; the backend creates the conversation on first sight.
      body: JSON.stringify({ message, domain_id: domainId, role, session_id: sessionId }),
    }),
  )
}

export async function addBusiness({ domainId, rootUrl, displayName, adminToken }) {
  // The admin token guards this write endpoint (FR-API-02); it rides in X-API-Key. Returns the
  // business in `pending` state — the crawl runs in the background, so poll getBusinessStatus.
  return jsonOrThrow(
    await fetch(`${API_BASE}/api/crawl/site`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': adminToken },
      body: JSON.stringify({
        domain_id: domainId,
        root_url: rootUrl,
        display_name: displayName || undefined,
      }),
    }),
  )
}

export async function getBusinessStatus(domainId) {
  return jsonOrThrow(await fetch(`${API_BASE}/api/crawl/site/${encodeURIComponent(domainId)}`))
}

export async function getConversations({ domainId, role }) {
  const q = new URLSearchParams({ domain_id: domainId, role })
  return jsonOrThrow(await fetch(`${API_BASE}/api/conversations?${q}`))
}

export async function getConversationHistory(sessionId) {
  return jsonOrThrow(
    await fetch(`${API_BASE}/api/chat/conversation/${encodeURIComponent(sessionId)}`),
  )
}

export async function ingestPrivateNote({ domainId, title, text, adminToken }) {
  // Staff-only private content. Admin-token-gated (X-API-Key) like the other ingestion writes;
  // the note is ingested as access_level=private, retrievable by staff, never by customers.
  return jsonOrThrow(
    await fetch(`${API_BASE}/api/ingest/private`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': adminToken },
      body: JSON.stringify({ domain_id: domainId, title, text }),
    }),
  )
}
