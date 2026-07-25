import { useRef, useState } from 'react'
import { api, describeApiError } from '../api'
import type { AgentResponse, ChatTurn } from '../types'
import { EvidenceDrawer } from './EvidenceDrawer'
import { StatusBadge } from './StatusBadge'

/**
 * 後端在 provider 重試後仍失敗、或熔斷開啟時,回的是這一句固定的 limitations
 * (agent/loop.py 的 _REFUSAL_LIMITATION_PROVIDER_UNAVAILABLE)。
 *
 * 這是刻意用文字比對而不是加一個新欄位:回應契約 AgentResponse 是這個專案的
 * 公開介面之一,為了前端的一個標籤就改它不划算。四個 limitations 常數都是
 * 固定字串,不含使用者輸入。
 */
const SERVICE_UNAVAILABLE_LIMITATION = 'AI 服務暫時無法回應,請稍後再試。'

function isServiceUnavailable(response: AgentResponse): boolean {
  return response.refused && response.limitations === SERVICE_UNAVAILABLE_LIMITATION
}

interface Props {
  patientId: string
  patientName: string
}

const SUGGESTIONS = ['他目前有在吃什麼藥?', '最近的觀察值是什麼?', '目前有哪些生效中的診斷?']

export function ChatPanel({ patientId, patientName }: Props) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLUListElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const submit = async (question: string) => {
    if (!question.trim()) return
    const id = crypto.randomUUID()
    setTurns((prev) => [...prev, { id, question, response: null, pending: true, error: null }])
    setDraft('')

    try {
      const response = await api.chat(patientId, question)
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, response, pending: false } : t)))
    } catch (err) {
      // 不直接顯示後端的 detail——照護人員要知道的是「現在該怎麼辦」,不是 HTTP 語意
      const message = describeApiError(err)
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, error: message, pending: false } : t)))
    } finally {
      queueMicrotask(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
      })
    }
  }

  const applySuggestion = (text: string) => {
    void submit(text)
    textareaRef.current?.focus()
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void submit(draft)
    }
  }

  return (
    <section className="chat-panel" aria-label={`與 ${patientName} 相關的問答`}>
      <header className="chat-panel__header">
        <h2>
          <span className="flow-step" aria-hidden="true">
            3
          </span>
          個案問答
        </h2>
        <p className="chart-panel__subline">
          只根據 {patientName} 的病歷資料回答,查無資料時會明確拒答,不會臆測
        </p>
      </header>

      <ul
        className={`chat-log${turns.length === 0 ? ' chat-log--empty' : ''}`}
        ref={listRef}
        aria-live="polite"
      >
        {turns.length === 0 && (
          <li className="chat-log__empty">
            <p className="chat-log__empty-title">想知道什麼,直接打字問</p>
            <p className="chat-log__empty-hint">或點一句開始:</p>
            <div className="chat-log__suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  className="suggestion-chip"
                  onClick={() => applySuggestion(s)}
                >
                  {s}
                </button>
              ))}
            </div>
            <span className="chat-log__empty-arrow" aria-hidden="true">
              問題輸入框在下面 ↓
            </span>
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
                {t.response.refused && (
                  // 「服務暫時不可用」和「資料不足所以拒答」是兩件不同的事。
                  // 都標成「拒答」的話,使用者會以為是自己的問題被回絕,而不是
                  // 系統暫時壞掉——前者不會想再試,後者會。
                  <span className="refusal-tag">
                    {isServiceUnavailable(t.response) ? '服務暫時無法使用' : '拒答'}
                  </span>
                )}
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
          void submit(draft)
        }}
      >
        <div className="chat-composer__field">
          <label htmlFor="chat-input">輸入問題</label>
          <textarea
            id="chat-input"
            ref={textareaRef}
            rows={2}
            placeholder="例如:他目前有在吃什麼藥?"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
          />
        </div>
        <button type="submit" className="btn btn--primary" disabled={!draft.trim()}>
          送出
        </button>
      </form>

      {turns.length === 0 && (
        <ul className="chat-trust-list">
          <li>
            <span className="chat-trust-list__icon chat-trust-list__icon--yes">✓</span>
            每個回答都附可查證的病歷證據(FHIR 資源與欄位)
          </li>
          <li>
            <span className="chat-trust-list__icon chat-trust-list__icon--yes">✓</span>
            資料不足時會明確拒答,不會臆測或編造
          </li>
          <li>
            <span className="chat-trust-list__icon chat-trust-list__icon--no">✕</span>
            不提供醫療診斷、用藥或治療建議
          </li>
        </ul>
      )}
    </section>
  )
}
