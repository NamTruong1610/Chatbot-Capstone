import { useCallback, useEffect, useState } from 'react'
import { getDomains, sendMessage } from './api.js'
import BusinessSelector from './components/BusinessSelector.jsx'
import RoleToggle from './components/RoleToggle.jsx'
import ChatWindow from './components/ChatWindow.jsx'
import AddBusinessForm from './components/AddBusinessForm.jsx'

export default function App() {
  const [domains, setDomains] = useState([])
  const [domainId, setDomainId] = useState('')
  const [role, setRole] = useState('customer')
  const [sessionId, setSessionId] = useState('')
  const [messages, setMessages] = useState([])
  const [error, setError] = useState('')
  const [adminToken, setAdminToken] = useState('') // kept in state so it isn't retyped per add

  const refreshDomains = useCallback(async () => {
    try {
      const data = await getDomains()
      setDomains(data.domains)
      // Default to the first ready business if nothing is selected yet.
      setDomainId((cur) => cur || data.domains.find((d) => d.status === 'ready')?.domain_id || '')
    } catch (e) {
      setError(`Could not load businesses — is the backend running on :8000? (${e.message})`)
    }
  }, [])

  useEffect(() => {
    refreshDomains()
  }, [refreshDomains])

  // Mint a fresh conversation whenever the domain OR role changes. A conversation's (domain, role)
  // is fixed at creation, so reusing a session_id across a switch would hit the backend's
  // fail-closed scope guard (403). New session = clean, correct conversation.
  useEffect(() => {
    setSessionId(crypto.randomUUID())
    setMessages([])
  }, [domainId, role])

  const handleSend = async (text) => {
    setError('')
    setMessages((prev) => [...prev, { sender: 'user', content: text }])
    try {
      const res = await sendMessage({ message: text, domainId, role, sessionId })
      setMessages((prev) => [
        ...prev,
        { sender: 'assistant', content: res.answer, sources: res.sources, grounded: res.grounded },
      ])
    } catch (e) {
      setMessages((prev) => [...prev, { sender: 'assistant', content: `⚠ ${e.message}`, error: true }])
    }
  }

  const newConversation = () => {
    setSessionId(crypto.randomUUID())
    setMessages([])
  }

  const selected = domains.find((d) => d.domain_id === domainId)
  const canChat = selected?.status === 'ready'
  const disabledReason = selected
    ? `“${selected.display_name}” is ${selected.status}, not ready to query`
    : 'Select a business first'

  return (
    <div className="app">
      <header>
        <h1>SME Chatbot</h1>
        <div className="controls">
          <BusinessSelector domains={domains} value={domainId} onChange={setDomainId} />
          <RoleToggle value={role} onChange={setRole} />
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

      <AddBusinessForm
        adminToken={adminToken}
        onAdminToken={setAdminToken}
        onDomainsChanged={refreshDomains}
        onReady={setDomainId}
      />

      <footer className="meta">
        domain <code>{domainId || '—'}</code> · role <code>{role}</code> · session{' '}
        <code>{sessionId ? sessionId.slice(0, 8) : '—'}</code>
      </footer>
    </div>
  )
}
