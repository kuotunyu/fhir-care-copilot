// 對應後端 Pydantic schema(src/fhir_copilot/api/schemas.py、tools/*.py、agent/response.py)。

export interface PatientSummaryItem {
  patient_id: string
  name: string
  gender: string | null
  birth_date: string | null
  source_file: string
}

export interface PatientDemographics {
  patient_id: string
  name: string
  gender: string | null
  birth_date: string | null
}

export interface ConditionSummary {
  display: string
  code_system: string | null
  code_value: string | null
  onset_date: string | null
}

export interface MedicationSummary {
  display: string
  code_system: string | null
  code_value: string | null
  authored_on: string | null
}

export interface ObservationSummary {
  display: string
  value_display: string | null
  effective_date: string | null
  category: string | null
}

export interface CarePlanSummary {
  display: string
  status: string | null
  period_start: string | null
  period_end: string | null
  activities: string[]
}

export interface PatientSummaryResponse {
  demographics: PatientDemographics | null
  conditions: ConditionSummary[]
  medications: MedicationSummary[]
  observations: ObservationSummary[]
  care_plans: CarePlanSummary[]
}

export interface Evidence {
  resource_type: string
  resource_id: string
  field: string | null
  value: string | null
}

export interface AgentResponse {
  answer: string
  evidence: Evidence[]
  limitations: string | null
  refused: boolean
  model: string
  latency_ms: number
  input_tokens: number
  output_tokens: number
  estimated_cost_usd: number
}

export interface HealthInfo {
  status: string
  provider: string
  model_id: string
  demo_mode: boolean
  patient_count: number
  // 營運層狀態:哪些保護開著、今日用了多少額度
  auth_required: boolean
  api_key_count: number
  rate_limit_per_minute: number
  budget_limit_usd: number
  budget_spent_usd_today: number
  /** 記憶體計數,重啟歸零——所以要一起顯示起算時間 */
  budget_counting_since: string
}

export interface CareNoteDraft {
  patient_id: string
  note_text: string
  proposed_at: string
}

export interface ConfirmedCareNote {
  patient_id: string
  note_text: string
  proposed_at: string
  confirmed_at: string
}

export interface ChatTurn {
  id: string
  question: string
  response: AgentResponse | null
  pending: boolean
  error: string | null
}
