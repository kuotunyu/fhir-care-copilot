import type { HealthInfo } from '../types'

export function StatusBar({ health }: { health: HealthInfo | null }) {
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
          <div className={`status-panel${health.demo_mode ? ' status-panel--demo' : ' status-panel--live'}`}>
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
            </div>
          </div>
        )}
      </div>
    </header>
  )
}
