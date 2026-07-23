import type { HealthInfo } from '../types'

export function StatusBar({ health }: { health: HealthInfo | null }) {
  return (
    <header className="app-header">
      <div className="app-header__brand">
        <span className="app-header__mark" aria-hidden="true">
          卡
        </span>
        <div>
          <h1>FHIR Care Copilot</h1>
          <p className="app-header__tagline">可追溯・工具受控・預設唯讀的長照個案查詢工作台</p>
        </div>
      </div>
      <div className="app-header__status">
        {health?.demo_mode && <span className="demo-pill">示範模式(未連線真實模型)</span>}
        {health && (
          <span className="provider-pill mono">
            {health.provider} · {health.model_id}
          </span>
        )}
      </div>
    </header>
  )
}
