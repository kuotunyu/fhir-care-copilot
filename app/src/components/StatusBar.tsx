import { useEffect, useState } from 'react'
import { getApiKey, setApiKey } from '../api'
import type { HealthInfo } from '../types'

interface Props {
  health: HealthInfo | null
  /** 存好金鑰後通知上層重新讀 health(認證狀態可能因此改變) */
  onApiKeyChange: () => void
}

export function StatusBar({ health, onApiKeyChange }: Props) {
  const [keyDraft, setKeyDraft] = useState(() => getApiKey())
  const [saved, setSaved] = useState(false)
  const [open, setOpen] = useState(false)

  // 伺服器端沒有設定任何金鑰、也沒要求認證時,這個控制項對使用者沒有意義,
  // 不要放在畫面上當雜訊。
  const showKeyControl = Boolean(health && (health.auth_required || health.api_key_count > 0))
  const hasKey = getApiKey().length > 0

  // 服務要求認證、但這台瀏覽器還沒設金鑰時自動展開。收合著的話,使用者要先
  // 送出一次問題被擋、再自己找到這個摺疊區塊才知道要做什麼——那是猜測成本
  // (PRODUCT.md:不能有猜測成本;輸入框要有清楚 affordance)。
  useEffect(() => {
    if (health?.auth_required && !getApiKey()) setOpen(true)
  }, [health?.auth_required])

  const save = (event: React.FormEvent) => {
    event.preventDefault()
    setApiKey(keyDraft.trim())
    setSaved(true)
    onApiKeyChange()
    window.setTimeout(() => setSaved(false), 2000)
  }

  const clear = () => {
    setApiKey('')
    setKeyDraft('')
    setSaved(false)
    onApiKeyChange()
  }

  return (
    <header className="app-header">
      <div className="app-header__brand">
        <span className="app-header__mark" aria-hidden="true">
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <rect x="9" y="1.5" width="6" height="3" rx="1" />
            <rect x="4" y="3" width="16" height="19" rx="2" />
            <path d="M6.5 13.5h2.5l1.5-4 2 8 1.5-4h3.5" />
          </svg>
        </span>
        <div>
          <h1>FHIR Care Copilot</h1>
          <p className="app-header__tagline">可追溯・工具受控・預設唯讀的長照個案查詢工作台</p>
        </div>
      </div>
      <div className="app-header__status">
        {health && (
          <div
            className={`status-panel${health.demo_mode ? ' status-panel--demo' : ' status-panel--live'}`}
          >
            <span className="status-panel__dot" aria-hidden="true" />
            <div className="status-panel__text">
              <p className="status-panel__title">
                {health.demo_mode ? '示範模式' : '已連線真實 AI 模型'}
              </p>
              <p className="status-panel__detail">
                {health.demo_mode
                  ? '尚未連接真實 AI,以下所有回答都是預先設定的模擬資料,僅供介面展示'
                  : `目前使用 ${health.provider} · ${health.model_id}`}
              </p>
              {!health.demo_mode && health.budget_limit_usd > 0 && (
                <p className="status-panel__detail">
                  今日用量 US${health.budget_spent_usd_today.toFixed(4)} / 上限 US$
                  {health.budget_limit_usd.toFixed(2)}
                  ・每分鐘上限 {health.rate_limit_per_minute} 次
                </p>
              )}
            </div>
          </div>
        )}

        {showKeyControl && (
          <details
            className="api-key"
            open={open}
            onToggle={(e) => setOpen(e.currentTarget.open)}
          >
            <summary className="api-key__summary">
              <span
                className={`api-key__dot${hasKey ? ' api-key__dot--set' : ''}`}
                aria-hidden="true"
              />
              API key:{hasKey ? '已設定' : '未設定'}
            </summary>
            <form className="api-key__form" onSubmit={save}>
              <label className="api-key__label" htmlFor="api-key-input">
                API key 只保留在目前頁面的記憶體,並隨 API 請求傳給此服務;重新整理或關閉頁面後會清除。
              </label>
              <div className="api-key__row">
                <input
                  id="api-key-input"
                  className="api-key__input"
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={keyDraft}
                  onChange={(e) => setKeyDraft(e.target.value)}
                  placeholder="例如 sk-..."
                />
                <button className="api-key__button" type="submit">
                  儲存
                </button>
                {hasKey && (
                  <button className="api-key__button api-key__button--ghost" type="button" onClick={clear}>
                    清除
                  </button>
                )}
              </div>
              <p className="api-key__hint" role="status">
                {saved ? '已儲存' : health?.auth_required ? '此服務目前要求認證' : ''}
              </p>
            </form>
          </details>
        )}
      </div>
    </header>
  )
}
