// The browse-and-resume sidebar (Phase 12). Lists past conversations for the current (domain, role)
// scope; clicking one resumes it (App adopts its session_id + messages, no reset). Titles are the
// first user message; previews the latest message — both from the backend.

function timeAgo(iso) {
  if (!iso) return ''
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const secs = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (secs < 60) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

export default function ConversationList({ conversations, activeSessionId, onResume }) {
  return (
    <div className="conversation-list">
      <h2>Past conversations</h2>
      {conversations.length === 0 ? (
        <p className="hint small">None in this scope yet.</p>
      ) : (
        <ul>
          {conversations.map((c) => (
            <li key={c.session_id}>
              <button
                type="button"
                className={`convo${c.session_id === activeSessionId ? ' active' : ''}`}
                onClick={() => onResume(c)}
              >
                <span className="convo-title">{c.title}</span>
                <span className="convo-preview">{c.preview}</span>
                <span className="convo-meta">
                  {timeAgo(c.updated_at)} · {c.message_count} msgs
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
