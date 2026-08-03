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
  /** 後端營運層回的機器可讀代碼(missing_api_key / rate_limited / budget_exceeded ...) */
  errorCode?: string
  /** 429 時後端建議的等待秒數 */
  retryAfterSeconds?: number
  /** budget_exceeded 時的用量資訊,給友善訊息用 */
  spentUsd?: number
  limitUsd?: number

  constructor(
    message: string,
    status: number,
    extras?: {
      errorCode?: string
      retryAfterSeconds?: number
      spentUsd?: number
      limitUsd?: number
    },
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.errorCode = extras?.errorCode
    this.retryAfterSeconds = extras?.retryAfterSeconds
    this.spentUsd = extras?.spentUsd
    this.limitUsd = extras?.limitUsd
  }
}

/**
 * API key 只保留在目前頁面的記憶體中。
 *
 * 不使用 localStorage/sessionStorage/cookie,避免金鑰在頁面生命週期外留存。
 * 模組初始化時 best-effort 移除舊版殘留的 localStorage 項目;儲存空間不可用
 * 時也不影響目前頁面的金鑰使用。
 */
const LEGACY_API_KEY_STORAGE_KEY = 'fhir-copilot.api-key'
let apiKey = ''

try {
  localStorage.removeItem(LEGACY_API_KEY_STORAGE_KEY)
} catch {
  // localStorage 不可用時仍可使用目前頁面的記憶體金鑰。
}

export function getApiKey(): string {
  return apiKey
}

export function setApiKey(key: string): void {
  apiKey = key
}

/** API key header 的名稱,要與 configs/ops.yaml 的 auth.header_name 一致。 */
const API_KEY_HEADER = 'X-API-Key'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // 唯一的金鑰注入點——6 個 API 呼叫全部走這裡
  const apiKey = getApiKey()
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { [API_KEY_HEADER]: apiKey } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let detail = response.statusText
    let extras: {
      errorCode?: string
      retryAfterSeconds?: number
      spentUsd?: number
      limitUsd?: number
    } = {}
    try {
      const body = (await response.json()) as {
        detail?: string
        error_code?: string
        retry_after_seconds?: number
        spent_usd?: number
        limit_usd?: number
      }
      if (body.detail) detail = body.detail
      extras = {
        errorCode: body.error_code,
        retryAfterSeconds: body.retry_after_seconds,
        spentUsd: body.spent_usd,
        limitUsd: body.limit_usd,
      }
    } catch {
      // 回應不是 JSON,用預設的 statusText
    }
    throw new ApiError(detail, response.status, extras)
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

/**
 * 把後端的拒絕翻成使用者看得懂的一句話。
 *
 * 直接吐後端的 detail 給照護人員看是不負責任的——他們要知道的是
 * 「我現在該怎麼辦」,不是 HTTP 語意。
 */
export function describeApiError(error: unknown): string {
  if (!(error instanceof ApiError)) return '網路連線失敗,請稍後再試。'

  switch (error.errorCode) {
    case 'missing_api_key':
      return '這項功能需要 API key。請在上方狀態列貼入你的金鑰後再試一次。'
    case 'invalid_api_key':
      return 'API key 無效。請確認金鑰是否正確,或清除後重新輸入。'
    case 'rate_limited': {
      const seconds = error.retryAfterSeconds
      return seconds
        ? `查詢太頻繁了,請等 ${seconds} 秒後再試。`
        : '查詢太頻繁了,請稍後再試。'
    }
    case 'budget_exceeded': {
      const usage =
        error.spentUsd !== undefined && error.limitUsd !== undefined
          ? `(已用 US$${error.spentUsd.toFixed(4)} / 上限 US$${error.limitUsd.toFixed(2)})`
          : ''
      return `今日查詢額度已用完${usage},額度會在每日 UTC 00:00 重置。`
    }
    case 'budget_unavailable': {
      // 用量計數暫時讀不到 → 後端 fail closed。對照護人員來說重點是
      // 「這是暫時的、稍後再試」,不是「稽核資料庫連不上」。
      const seconds = error.retryAfterSeconds
      return seconds
        ? `服務暫時無法處理查詢,請等 ${seconds} 秒後再試。`
        : '服務暫時無法處理查詢,請稍後再試。'
    }
    default:
      break
  }

  if (error.status === 401) return '需要有效的 API key 才能使用這項功能。'
  if (error.status === 429) return '目前無法處理更多查詢,請稍後再試。'
  if (error.status >= 500) return '服務暫時無法回應,請稍後再試。'
  return error.message
}

export { ApiError }
