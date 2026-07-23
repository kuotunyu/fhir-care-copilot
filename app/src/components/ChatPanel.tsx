import { useRef, useState } from 'react'
import { api, ApiError } from '../api'
import type { ChatTurn } from '../types'
import { EvidenceDrawer } from './EvidenceDrawer'
import { StatusBadge } from './StatusBadge'

interface Props {
  patientId: string
  patientName: string
}

export function ChatPanel({ patientId, patientName }: Props) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLUListElement>(null)

  const submit = async () => {
    const question = draft.trim()
    if (!question) return
    const id = crypto.randomUUID()
    setTurns((prev) => [...prev, { id, question, response: null, pending: true, error: null }])
    setDraft('')

    try {
      const response = await api.chat(patientId, question)
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, response, pending: false } : t)))
    } catch (err) {
      const message = err instanceof ApiError ? err.message : '網路連線失敗,請稍後再試。'
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, error: message, pending: false } : t)))
    } finally {
      queueMicrotask(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
      })
    }
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void submit()
    }
  }

  return (
    <section className="chat-panel" aria-label={`與 ${patientName} 相關的問答`}>
      <header className="chat-panel__header">
        <h2>個案問答</h2>
        <p className="chart-panel__subline">
          只根據 {patientName} 的病歷資料回答,查無資料時會明確拒答,不會臆測
        </p>
      </header>

      <ul className="chat-log" ref={listRef} aria-live="polite">
        {turns.length === 0 && (
          <li className="chat-log__hint">
            試著問:「他目前有在吃什麼藥?」「最近的觀察值是什麼?」
          </li>
        )}
        {turns.map((t) => (
          <li key={t.id} className="chat-turn">
            <div className="chat-bubble chat-bubble--question">{t.question}</div>
            {t.pending && (
              <div className="chat-bubble chat-bubble--answer chat-bubble--pending">
                <span className="thinking-dot" />
                <span className="thinking-dot" />
                <span className="thinking-dot" />
              </div>
            )}
            {t.error && (
              <div className="chat-bubble chat-bubble--answer chat-bubble--error">{t.error}</div>
            )}
            {t.response && (
              <div
                className={`chat-bubble chat-bubble--answer${t.response.refused ? ' chat-bubble--refused' : ''}`}
              >
                {t.response.refused && <span className="refusal-tag">拒答</span>}
                <p className="chat-bubble__text">{t.response.answer}</p>
                {t.response.limitations && (
                  <p className="chat-bubble__limitations">{t.response.limitations}</p>
                )}
                <div className="chat-bubble__footer">
                  <StatusBadge response={t.response} />
                  <EvidenceDrawer evidence={t.response.evidence} />
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <label className="sr-only" htmlFor="chat-input">
          輸入問題
        </label>
        <textarea
          id="chat-input"
          rows={2}
          placeholder="輸入問題,Enter 送出、Shift+Enter 換行…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <button type="submit" className="btn btn--primary" disabled={!draft.trim()}>
          送出
        </button>
      </form>
    </section>
  )
}
