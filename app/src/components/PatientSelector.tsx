import { useMemo, useState } from 'react'
import type { PatientSummaryItem } from '../types'

interface Props {
  patients: PatientSummaryItem[]
  selectedId: string | null
  onSelect: (patientId: string) => void
  loading: boolean
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
        <h2>個案清單</h2>
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
                <span className="patient-card__avatar" aria-hidden="true">
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
