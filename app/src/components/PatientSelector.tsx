import { useMemo, useState } from 'react'
import type { PatientSummaryItem } from '../types'

interface Props {
  patients: PatientSummaryItem[]
  selectedId: string | null
  onSelect: (patientId: string) => void
  loading: boolean
}

const AVATAR_PALETTES = ['teal', 'terracotta', 'amber'] as const

// 頭像底色依病患 id 輪流分配(不是隨機,同一位病患每次重新整理都拿到同一個
// 顏色)——原本全部都是同一色的圓圈+姓名首字,病患清單按姓氏排序時常常
// 連續一排都是同一個字母,看起來像所有人共用同一個意義不明的標籤。
// 換顏色後才看得出「這是每個人自己的頭像」,不是一個分類徽章。
function avatarPalette(patientId: string): (typeof AVATAR_PALETTES)[number] {
  let hash = 0
  for (let i = 0; i < patientId.length; i++) {
    hash = (hash * 31 + patientId.charCodeAt(i)) >>> 0
  }
  return AVATAR_PALETTES[hash % AVATAR_PALETTES.length]
}

export function PatientSelector({ patients, selectedId, onSelect, loading }: Props) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return patients
    return patients.filter((p) => p.name.toLowerCase().includes(q))
  }, [patients, query])

  return (
    <section className="patient-rail" aria-label="病患選擇器">
      <div className="patient-rail__header">
        <h2>
          <span className="flow-step" aria-hidden="true">
            1
          </span>
          個案清單
        </h2>
        <span className="patient-rail__count mono">{patients.length}</span>
      </div>
      <label className="patient-rail__search">
        <span className="sr-only">搜尋病患姓名</span>
        <input
          type="search"
          placeholder="搜尋姓名…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {loading ? (
        <p className="patient-rail__empty">載入病患清單中…</p>
      ) : filtered.length === 0 ? (
        <p className="patient-rail__empty">查無符合的病患</p>
      ) : (
        <ul className="patient-rail__list" role="listbox" aria-label="病患">
          {filtered.map((p, i) => (
            <li key={p.patient_id} style={{ animationDelay: `${Math.min(i, 12) * 22}ms` }}>
              <button
                type="button"
                role="option"
                aria-selected={p.patient_id === selectedId}
                className={`patient-card${p.patient_id === selectedId ? ' is-selected' : ''}`}
                onClick={() => onSelect(p.patient_id)}
              >
                <span
                  className={`patient-card__avatar patient-card__avatar--${avatarPalette(p.patient_id)}`}
                  aria-hidden="true"
                >
                  {p.name.trim().charAt(0) || '?'}
                </span>
                <span className="patient-card__meta">
                  <span className="patient-card__name">{p.name}</span>
                  <span className="patient-card__sub">
                    {p.gender === 'female' ? '女' : p.gender === 'male' ? '男' : '性別未記錄'}
                    {p.birth_date ? ` · ${p.birth_date}` : ''}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
