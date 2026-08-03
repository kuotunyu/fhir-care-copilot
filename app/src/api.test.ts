import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, describeApiError, getApiKey, setApiKey } from './api'

function mockFetchOnce(init: {
  ok?: boolean
  status?: number
  statusText?: string
  json?: unknown
  jsonThrows?: boolean
}) {
  const response = {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: init.statusText ?? 'OK',
    json: init.jsonThrows
      ? () => Promise.reject(new Error('not json'))
      : () => Promise.resolve(init.json ?? {}),
  }
  const spy = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', spy)
  return spy
}

afterEach(() => {
  setApiKey('')
  window.localStorage.clear()
  window.sessionStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('API key 的頁面生命週期', () => {
  it('只保留在目前頁面的記憶體,不寫入 Web Storage', () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem')

    setApiKey('demo-key')

    expect(getApiKey()).toBe('demo-key')
    expect(setItem).not.toHaveBeenCalled()
  })

  it('存空字串等於清除', () => {
    setApiKey('demo-key')
    setApiKey('')
    expect(getApiKey()).toBe('')
  })

  it('重新載入模組後不保留金鑰', async () => {
    setApiKey('page-only-secret')
    vi.resetModules()

    const freshApi = await import('./api')

    expect(freshApi.getApiKey()).toBe('')
  })

  it('不讀取舊的 localStorage key,但會嘗試移除它', async () => {
    const getItem = vi.spyOn(Storage.prototype, 'getItem')
    const removeItem = vi.spyOn(Storage.prototype, 'removeItem')
    vi.resetModules()

    const freshApi = await import('./api')

    expect(freshApi.getApiKey()).toBe('')
    expect(getItem).not.toHaveBeenCalled()
    expect(removeItem).toHaveBeenCalledWith('fhir-copilot.api-key')
  })

  it('localStorage 不可用時仍能使用頁面記憶體', async () => {
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage')
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('localStorage 被停用')
      },
    })
    try {
      vi.resetModules()
      const freshApi = await import('./api')
      expect(freshApi.getApiKey()).toBe('')
      expect(() => freshApi.setApiKey('page-only')).not.toThrow()
      expect(freshApi.getApiKey()).toBe('page-only')
    } finally {
      if (original) Object.defineProperty(window, 'localStorage', original)
    }
  })
})

describe('request 的金鑰注入', () => {
  it('有金鑰時每個呼叫都帶上 X-API-Key', async () => {
    setApiKey('secret-key')
    const spy = mockFetchOnce({ json: { patients: [] } })

    await api.listPatients()

    const headers = spy.mock.calls[0][1].headers as Record<string, string>
    expect(headers['X-API-Key']).toBe('secret-key')
  })

  it('沒有金鑰時不送這個 header——不是送空字串', async () => {
    const spy = mockFetchOnce({ json: { patients: [] } })

    await api.listPatients()

    const headers = spy.mock.calls[0][1].headers as Record<string, string>
    expect('X-API-Key' in headers).toBe(false)
  })

  it('金鑰注入點只有一個,POST 也一樣帶上', async () => {
    setApiKey('secret-key')
    const spy = mockFetchOnce({ json: {} })

    await api.chat('patient-1', '他在吃什麼藥?')

    const headers = spy.mock.calls[0][1].headers as Record<string, string>
    expect(headers['X-API-Key']).toBe('secret-key')
    expect(spy.mock.calls[0][1].method).toBe('POST')
  })
})

describe('錯誤回應的解析', () => {
  it('把後端的結構化欄位帶進 ApiError', async () => {
    mockFetchOnce({
      ok: false,
      status: 429,
      json: {
        detail: '請求太頻繁,請稍後再試。',
        error_code: 'rate_limited',
        retry_after_seconds: 12,
      },
    })

    const error = await api.chat('p', 'q').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.status).toBe(429)
    expect(apiError.errorCode).toBe('rate_limited')
    expect(apiError.retryAfterSeconds).toBe(12)
  })

  it('回應不是 JSON 時退回 statusText,不會在解析階段炸掉', async () => {
    mockFetchOnce({ ok: false, status: 502, statusText: 'Bad Gateway', jsonThrows: true })

    const error = (await api.health().catch((e: unknown) => e)) as ApiError

    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(502)
    expect(error.message).toBe('Bad Gateway')
  })
})

describe('describeApiError:給照護人員看的一句話', () => {
  it.each([
    ['missing_api_key', '需要 API key'],
    ['invalid_api_key', 'API key 無效'],
    ['budget_unavailable', '服務暫時無法處理查詢'],
  ])('%s 翻成可行動的說明', (code, expected) => {
    const message = describeApiError(new ApiError('後端原文', 401, { errorCode: code }))
    expect(message).toContain(expected)
  })

  it('限流時把後端建議的秒數放進訊息', () => {
    const message = describeApiError(
      new ApiError('rate limited', 429, { errorCode: 'rate_limited', retryAfterSeconds: 30 }),
    )
    expect(message).toContain('30 秒')
  })

  it('限流但後端沒給秒數時不會出現 undefined', () => {
    const message = describeApiError(new ApiError('rate limited', 429, { errorCode: 'rate_limited' }))
    expect(message).not.toContain('undefined')
    expect(message).toContain('稍後再試')
  })

  it('預算用完時顯示用量與上限', () => {
    const message = describeApiError(
      new ApiError('budget', 429, {
        errorCode: 'budget_exceeded',
        spentUsd: 1.0,
        limitUsd: 1.0,
      }),
    )
    expect(message).toContain('US$1.0000')
    expect(message).toContain('US$1.00')
  })

  it('預算用完但沒帶用量時不會印出半截括號', () => {
    const message = describeApiError(new ApiError('budget', 429, { errorCode: 'budget_exceeded' }))
    expect(message).not.toContain('(')
    expect(message).not.toContain('undefined')
  })

  it('沒有 error_code 時退回依 HTTP 狀態碼判斷', () => {
    expect(describeApiError(new ApiError('x', 401))).toContain('API key')
    expect(describeApiError(new ApiError('x', 503))).toContain('服務暫時無法回應')
  })

  it('不是 ApiError(例如 fetch 直接失敗)也要給得出一句話', () => {
    expect(describeApiError(new TypeError('Failed to fetch'))).toContain('網路連線失敗')
  })
})
