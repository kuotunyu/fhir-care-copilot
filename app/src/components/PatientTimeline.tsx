import { useState } from 'react'
import type { PatientSummaryResponse } from '../types'

interface Props {
  summary: PatientSummaryResponse | null
  loading: boolean
  error: string | null
}

type TabKey = 'conditions' | 'medications' | 'observations' | 'careplan'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'conditions', label: '診斷' },
  { key: 'medications', label: '用藥' },
  { key: 'observations', label: '觀察值' },
  { key: 'careplan', label: '照護計畫' },
]

export function PatientTimeline({ summary, loading, error }: Props) {
  const [tab, setTab] = useState<TabKey>('conditions')

  if (loading) {
    return (
      <section className="chart-panel" aria-label="病歷摘要">
        <p className="chart-panel__empty">載入病歷資料中…</p>
      </section>
    )
  }

  if (error) {
    return (
      <section className="chart-panel" aria-label="病歷摘要">
        <p className="chart-panel__empty chart-panel__empty--error">{error}</p>
      </section>
    )
  }

  if (!summary) {
    return (
      <section className="chart-panel" aria-label="病歷摘要">
        <p className="chart-panel__empty">從左側選擇一位病患開始</p>
      </section>
    )
  }

  const counts: Record<TabKey, number> = {
    conditions: summary.conditions.length,
    medications: summary.medications.length,
    observations: summary.observations.length,
    careplan: summary.care_plans.length,
  }

  return (
    <section className="chart-panel" aria-label="病歷摘要">
      <header className="chart-panel__header">
        <p className="panel-eyebrow">
          <span className="flow-step" aria-hidden="true">
            2
          </span>
          病歷時間軸
        </p>
        <h2>{summary.demographics?.name ?? '病患'}</h2>
        <p className="chart-panel__subline">
          {summary.demographics?.gender === 'female'
            ? '女性'
            : summary.demographics?.gender === 'male'
              ? '男性'
              : '性別未記錄'}
          {summary.demographics?.birth_date ? ` · 出生於 ${summary.demographics.birth_date}` : ''}
        </p>
      </header>

      <div className="chart-tabs" role="tablist" aria-label="病歷分類">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={`chart-tab${tab === t.key ? ' is-active' : ''}`}
            onClick={() => setTab(t.key)}
          >
            {t.label}
            <span className="chart-tab__count mono">{counts[t.key]}</span>
          </button>
        ))}
      </div>

      <div className="chart-panel__body" role="tabpanel">
        {tab === 'conditions' &&
          (summary.conditions.length === 0 ? (
            <EmptyRow text="目前沒有生效中的診斷記錄" />
          ) : (
            <ul className="record-list">
              {summary.conditions.map((c, i) => (
                <li key={i} className="record-row">
                  <span className="record-row__dot" style={{ background: 'var(--terracotta)' }} />
                  <div>
                    <p className="record-row__title">{c.display}</p>
                    <p className="record-row__meta">
                      {c.onset_date ? `發病日期 ${c.onset_date}` : '發病日期未記錄'}
                      {c.code_value ? ` · SNOMED ${c.code_value}` : ''}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ))}

        {tab === 'medications' &&
          (summary.medications.length === 0 ? (
            <EmptyRow text="目前沒有生效中的用藥記錄" />
          ) : (
            <ul className="record-list">
              {summary.medications.map((m, i) => (
                <li key={i} className="record-row">
                  <span className="record-row__dot" style={{ background: 'var(--teal)' }} />
                  <div>
                    <p className="record-row__title">{m.display}</p>
                    <p className="record-row__meta">
                      {m.authored_on ? `開立於 ${m.authored_on}` : '開立日期未記錄'}
                      {m.code_value ? ` · RxNorm ${m.code_value}` : ''}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ))}

        {tab === 'observations' &&
          (summary.observations.length === 0 ? (
            <EmptyRow text="查無觀察值記錄" />
          ) : (
            <ul className="record-list">
              {summary.observations.map((o, i) => (
                <li key={i} className="record-row">
                  <span className="record-row__dot" style={{ background: 'var(--amber)' }} />
                  <div>
                    <p className="record-row__title">
                      {o.display}
                      {o.value_display ? (
                        <span className="record-row__value mono"> {o.value_display}</span>
                      ) : null}
                    </p>
                    <p className="record-row__meta">
                      {o.effective_date ? o.effective_date : '日期未記錄'}
                      {o.category ? ` · ${o.category}` : ''}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          ))}

        {tab === 'careplan' &&
          (summary.care_plans.length === 0 ? (
            <EmptyRow text="目前沒有照護計畫記錄" />
          ) : (
            <ul className="record-list">
              {summary.care_plans.map((cp, i) => (
                <li key={i} className="record-row">
                  <span
                    className={`status-chip status-chip--${cp.status === 'active' ? 'active' : 'closed'}`}
                  >
                    {cp.status === 'active' ? '進行中' : cp.status || '狀態未記錄'}
                  </span>
                  <div>
                    <p className="record-row__title">{cp.display}</p>
                    <p className="record-row__meta">
                      {cp.period_start ? `${cp.period_start} 起` : '起始日期未記錄'}
                      {cp.period_end ? ` — ${cp.period_end} 止` : ''}
                    </p>
                    {cp.activities.length > 0 && (
                      <p className="record-row__activities">
                        活動:{cp.activities.join('、')}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          ))}
      </div>
    </section>
  )
}

function EmptyRow({ text }: { text: string }) {
  return <p className="chart-panel__empty">{text}</p>
}
