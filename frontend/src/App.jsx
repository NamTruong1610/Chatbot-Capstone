import { useCallback, useEffect, useState } from 'react'
import { getConversationHistory, getConversations, getDomains, sendMessage } from './api.js'
import BusinessSelector from './components/BusinessSelector.jsx'
import RoleToggle from './components/RoleToggle.jsx'
import ChatWindow from './components/ChatWindow.jsx'
import AddBusinessForm from './components/AddBusinessForm.jsx'
import AddPrivateNote from './components/AddPrivateNote.jsx'
import ConversationList from './components/ConversationList.jsx'

export default function App() {
  const [domains, setDomains] = useState([])
  const [domainId, setDomainId] = useState('')
  const [role, setRole] = useState('customer')
  // Minted once here; thereafter a NEW session is minted only on an explicit user switch
  // (changeDomain/changeRole/newConversation). Resuming ADOPTS a session and must not reset —
  // so the reset lives in those handlers, never in an effect that fires when domain/role change.
  const [sessionId, setSessionId] = useState(() => crypto.randomUUID())
  const [messages, setMessages] = useState([])
  const [conversations, setConversations] = useState([])
  const [error, setError] = useState('')
  const [adminToken, setAdminToken] = useState('')

  const refreshDomains = useCallback(async () => {
    try {
      const data = await getDomains()
      setDomains(data.domains)
      setDomainId((cur) => cur || data.domains.find((d) => d.status === 'ready')?.domain_id || '')
    } catch (e) {
      setError(`Could not load businesses — is the backend running on :8000? (${e.message})`)
    }
  }, [])

  // The conversation browser reacts to the current scope. This only re-fetches the LIST — it never
  // touches sessionId/messages, so it is safe to fire when a resume changes domain/role.
  const refreshConversations = useCallback(async () => {
    if (!domainId) return
    try {
      const data = await getConversations({ domainId, role })
      setConversations(data.conversations)
    } catch {
      // a missing list is not fatal to chatting; leave the sidebar as-is
    }
  }, [domainId, role])

  useEffect(() => {
    refreshDomains()
  }, [refreshDomains])

  useEffect(() => {
    refreshConversations()
  }, [refreshConversations])

  // Explicit resets — a user-driven scope switch starts a fresh conversation (the (domain, role)
  // scope is fixed per conversation, so a reused session across a switch would 403).
  const changeDomain = (d) => {
    setDomainId(d)
    setSessionId(crypto.randomUUID())
    setMessages([])
  }
  const changeRole = (r) => {
    setRole(r)
    setSessionId(crypto.randomUUID())
    setMessages([])
  }
  const newConversation = () => {
    setSessionId(crypto.randomUUID())
    setMessages([])
  }

  // Resume ADOPTS the conversation's scope + session + messages, all at once and WITHOUT going
  // through changeDomain/changeRole — so no reset fires and the next message continues it (no 403).
  const resumeConversation = async (summary) => {
    setError('')
    try {
      const history = await getConversationHistory(summary.session_id)
      setDomainId(summary.domain_id)
      setRole(summary.role)
      setSessionId(summary.session_id)
      setMessages(
        history.messages.map((m) => ({
          sender: m.sender,
          content: m.content,
          sources: m.sources || [],
          grounded: m.grounded,
        })),
      )
    } catch (e) {
      setError(`Could not resume conversation: ${e.message}`)
    }
  }

  const handleSend = async (text) => {
    setError('')
    setMessages((prev) => [...prev, { sender: 'user', content: text }])
    try {
      const res = await sendMessage({ message: text, domainId, role, sessionId })
      setMessages((prev) => [
        ...prev,
        { sender: 'assistant', content: res.answer, sources: res.sources, grounded: res.grounded },
      ])
      refreshConversations() // the active conversation now appears/updates in the sidebar
    } catch (e) {
      setMessages((prev) => [...prev, { sender: 'assistant', content: `⚠ ${e.message}`, error: true }])
    }
  }

  const selected = domains.find((d) => d.domain_id === domainId)
  const canChat = selected?.status === 'ready'
  const disabledReason = selected
    ? `“${selected.display_name}” is ${selected.status}, not ready to query`
    : 'Select a business first'

  return (
    <div className="app">
      <aside className="sidebar">
        <ConversationList
          conversations={conversations}
          activeSessionId={sessionId}
          onResume={resumeConversation}
        />
      </aside>

      <main className="main">
        <header>
          <h1>SME Chatbot</h1>
          <div className="controls">
            <BusinessSelector domains={domains} value={domainId} onChange={changeDomain} />
            <RoleToggle value={role} onChange={changeRole} />
            <button type="button" className="secondary" onClick={newConversation}>
              New conversation
            </button>
          </div>
        </header>

        {error && <div className="error-banner">{error}</div>}

        <ChatWindow
          messages={messages}
          onSend={handleSend}
          canChat={canChat}
          disabledReason={disabledReason}
        />

        {role === 'staff' && (
          <AddPrivateNote domainId={domainId} adminToken={adminToken} onAdminToken={setAdminToken} />
        )}

        <AddBusinessForm
          adminToken={adminToken}
          onAdminToken={setAdminToken}
          onDomainsChanged={refreshDomains}
          onReady={changeDomain}
        />

        <footer className="meta">
          domain <code>{domainId || '—'}</code> · role <code>{role}</code> · session{' '}
          <code>{sessionId ? sessionId.slice(0, 8) : '—'}</code>
        </footer>
      </main>
    </div>
  )
}
