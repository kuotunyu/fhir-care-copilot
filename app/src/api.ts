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
 * API key 存在 localStorage,由使用者在介面上貼入。
 *
 * 為什麼不是 build-time env:那會把金鑰烤進公開的 JS bundle,任何人打開
 * devtools 都讀得到——對一個以安全紀律為賣點的專案是自相矛盾的。
 * 放 localStorage 沒有比較「安全」(同源指令碼一樣讀得到),但它誠實:
 * 金鑰是這個瀏覽器的使用者自己提供的,不是我們發佈出去的。
 */
const API_KEY_STORAGE_KEY = 'fhir-copilot.api-key'

export function getApiKey(): string {
  try {
    return localStorage.getItem(API_KEY_STORAGE_KEY) ?? ''
  } catch {
    // 隱私模式等情境下 localStorage 可能不可用——沒有 key 就當作沒設
    return ''
  }
}

export function setApiKey(key: string): void {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE_KEY, key)
    else localStorage.removeItem(API_KEY_STORAGE_KEY)
  } catch {
    // 存不進去不該讓操作失敗;這一頁的 request 仍會帶上剛輸入的值
  }
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
