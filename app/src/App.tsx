import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { api } from './api'
import { ChatPanel } from './components/ChatPanel'
import { PatientSelector } from './components/PatientSelector'
import { PatientTimeline } from './components/PatientTimeline'
import { StatusBar } from './components/StatusBar'
import type { HealthInfo, PatientSummaryItem, PatientSummaryResponse } from './types'

function App() {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [patients, setPatients] = useState<PatientSummaryItem[]>([])
  const [patientsLoading, setPatientsLoading] = useState(true)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [summary, setSummary] = useState<PatientSummaryResponse | null>(null)
  const [summaryLoading, setSummaryLoading] = useState(false)
  const [summaryError, setSummaryError] = useState<string | null>(null)

  const refreshHealth = useCallback(() => {
    api
      .health()
      .then(setHealth)
      .catch(() => setHealth(null))
  }, [])

  useEffect(() => {
    refreshHealth()
    api
      .listPatients()
      .then((list) => {
        setPatients(list)
        if (list.length > 0) setSelectedId(list[0].patient_id)
      })
      .catch(() => setPatients([]))
      .finally(() => setPatientsLoading(false))
  }, [refreshHealth])

  useEffect(() => {
    if (!selectedId) return
    setSummaryLoading(true)
    setSummaryError(null)
    api
      .patientSummary(selectedId)
      .then(setSummary)
      .catch(() => setSummaryError('無法載入這位病患的病歷資料,請稍後再試。'))
      .finally(() => setSummaryLoading(false))
  }, [selectedId])

  const selectedPatient = patients.find((p) => p.patient_id === selectedId) ?? null

  return (
    <div className="app-shell">
      <StatusBar health={health} onApiKeyChange={refreshHealth} />

      <main className="app-main">
        <PatientSelector
          patients={patients}
          selectedId={selectedId}
          onSelect={setSelectedId}
          loading={patientsLoading}
        />
        <PatientTimeline summary={summary} loading={summaryLoading} error={summaryError} />
        {selectedPatient ? (
          <ChatPanel
            key={selectedPatient.patient_id}
            patientId={selectedPatient.patient_id}
            patientName={selectedPatient.name}
          />
        ) : (
          <section className="chat-panel chat-panel--empty" aria-label="個案問答">
            <p className="chart-panel__empty">選擇病患後即可開始問答</p>
          </section>
        )}
      </main>

      <footer className="app-footer">
        <p>
          合成資料展示，<strong>不是醫療診斷工具</strong>
          。所有回答均由結構化工具查詢病歷資料產生，並附上可追溯證據；資料不足時會明確拒答。
        </p>
      </footer>
    </div>
  )
}

export default App
