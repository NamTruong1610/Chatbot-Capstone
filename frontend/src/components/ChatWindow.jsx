import { useState } from 'react'

// The conversation transcript + composer. Each assistant turn shows a grounded/no-answer badge and
// its source URLs — the trust signals of strict-grounded generation. The composer is disabled when
// the selected business is not ready (so a query never 404s mid-demo).
export default function ChatWindow({ messages, onSend, canChat, disabledReason }) {
  const [input, setInput] = useState('')

  const submit = (e) => {
    e.preventDefault()
    const text = input.trim()
    if (!text || !canChat) return
    onSend(text)
    setInput('')
  }

  return (
    <div className="chat">
      <div className="messages">
        {messages.length === 0 && (
          <p className="hint">Ask a question about the selected business.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.sender}`}>
            <div className={`bubble${m.error ? ' error' : ''}`}>
              <div className="content">{m.content}</div>
              {m.sender === 'assistant' && !m.error && (
                <div className="answer-meta">
                  <span className={`badge ${m.grounded ? 'grounded' : 'ungrounded'}`}>
                    {m.grounded ? 'grounded' : 'no answer'}
                  </span>
                  {m.sources?.length > 0 && (
                    <ul className="sources">
                      {m.sources.map((s, j) => (
                        <li key={j}>
                          <a href={s} target="_blank" rel="noreferrer">{s}</a>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <form onSubmit={submit} className="composer">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={canChat ? 'Type a message…' : disabledReason}
          disabled={!canChat}
        />
        <button type="submit" disabled={!canChat || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
