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
