import type {
  AgentResponse,
  CareNoteDraft,
  ConfirmedCareNote,
  HealthInfo,
  PatientSummaryItem,
  PatientSummaryResponse,
} from './types'

class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: string }
      if (body.detail) detail = body.detail
    } catch {
      // 回應不是 JSON,用預設的 statusText
    }
    throw new ApiError(detail, response.status)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<HealthInfo>('/api/health'),

  listPatients: () =>
    request<{ patients: PatientSummaryItem[] }>('/api/patients').then((r) => r.patients),

  patientSummary: (patientId: string) =>
    request<PatientSummaryResponse>(`/api/patients/${encodeURIComponent(patientId)}/summary`),

  chat: (patientId: string, question: string) =>
    request<AgentResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ patient_id: patientId, question }),
    }),

  proposeCareNote: (patientId: string, noteText: string) =>
    request<{ ok: boolean; draft: CareNoteDraft | null }>('/api/care-notes/propose', {
      method: 'POST',
      body: JSON.stringify({ patient_id: patientId, note_text: noteText }),
    }),

  confirmCareNote: (draft: CareNoteDraft) =>
    request<ConfirmedCareNote>('/api/care-notes/confirm', {
      method: 'POST',
      body: JSON.stringify({ draft }),
    }),
}

export { ApiError }
