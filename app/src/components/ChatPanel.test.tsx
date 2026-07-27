import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ChatPanel } from './ChatPanel'
import type { AgentResponse } from '../types'

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}) {
  return {
    ok: init.ok ?? true,
    status: init.status ?? 200,
    statusText: 'OK',
    json: () => Promise.resolve(body),
  }
}

function answer(overrides: Partial<AgentResponse> = {}): AgentResponse {
  return {
    answer: '他目前在服用 Metformin。',
    evidence: [
      { resource_type: 'MedicationRequest', resource_id: 'med-1', field: 'status', value: 'active' },
    ],
    limitations: null,
    refused: false,
    refusal_reason: null,
    model: 'gemini-3.1-flash-lite',
    latency_ms: 1200,
    input_tokens: 1456,
    output_tokens: 112,
    estimated_cost_usd: 0.000532,
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

async function ask(question = '他目前有在吃什麼藥?') {
  const user = userEvent.setup()
  render(<ChatPanel patientId="p-1" patientName="Amy" />)
  await user.type(screen.getByRole('textbox'), question)
  await user.keyboard('{Enter}')
}

describe('ChatPanel 的回答呈現', () => {
  it('成功時顯示答案', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(answer())))

    await ask()

    await waitFor(() => expect(screen.getByText(/Metformin/)).toBeTruthy())
  })

  it('結構化拒答要把 limitations 顯示出來,不能只說「無法回答」', async () => {
    // 拒答的價值全在「為什麼」。只顯示 answer 的話,使用者不知道是資料不足、
    // 超出範圍、還是服務壞了——那三件事該做的下一步完全不同。
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          answer({
            answer: '很抱歉,目前無法回答這個問題。',
            evidence: [],
            refused: true,
            refusal_reason: 'out_of_scope',
            limitations: '這個問題超出可查詢的資料範圍,無法在有證據的前提下回答。',
          }),
        ),
      ),
    )

    await ask('他上次住院是什麼時候?')

    await waitFor(() => expect(screen.getByText(/超出可查詢的資料範圍/)).toBeTruthy())
  })
})

/**
 * 這一組守的是 Phase 1 建立的契約:**後端的 detail 不直接給照護人員看**。
 * 他們要知道的是「我現在該怎麼辦」,不是 HTTP 語意。
 */
describe('ChatPanel 的錯誤訊息', () => {
  it('限流時顯示可行動的等待秒數,而不是後端原文', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: 'Rate limit exceeded', error_code: 'rate_limited', retry_after_seconds: 30 },
          { ok: false, status: 429 },
        ),
      ),
    )

    await ask()

    await waitFor(() => expect(screen.getByText(/請等 30 秒後再試/)).toBeTruthy())
    expect(screen.queryByText(/Rate limit exceeded/)).toBeNull()
  })

  it('缺 API key 時告訴使用者去哪裡貼', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: 'missing api key', error_code: 'missing_api_key' },
          { ok: false, status: 401 },
        ),
      ),
    )

    await ask()

    await waitFor(() => expect(screen.getByText(/上方狀態列/)).toBeTruthy())
  })

  it('額度用完時說明何時重置,不是叫人「稍後再試」了事', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          { detail: 'budget', error_code: 'budget_exceeded', spent_usd: 1, limit_usd: 1 },
          { ok: false, status: 429 },
        ),
      ),
    )

    await ask()

    await waitFor(() => expect(screen.getByText(/UTC 00:00 重置/)).toBeTruthy())
  })

  it('網路整個失敗(fetch reject)也要給得出一句話,不是空白', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))

    await ask()

    await waitFor(() => expect(screen.getByText(/網路連線失敗/)).toBeTruthy())
  })
})

describe('ChatPanel 的送出行為', () => {
  it('空白輸入不會送出請求', async () => {
    const spy = vi.fn().mockResolvedValue(jsonResponse(answer()))
    vi.stubGlobal('fetch', spy)
    const user = userEvent.setup()
    render(<ChatPanel patientId="p-1" patientName="Amy" />)

    await user.type(screen.getByRole('textbox'), '   ')
    await user.keyboard('{Enter}')

    expect(spy).not.toHaveBeenCalled()
  })

  it('Shift+Enter 是換行,不是送出', async () => {
    const spy = vi.fn().mockResolvedValue(jsonResponse(answer()))
    vi.stubGlobal('fetch', spy)
    const user = userEvent.setup()
    render(<ChatPanel patientId="p-1" patientName="Amy" />)

    await user.type(screen.getByRole('textbox'), '他在吃什麼藥?')
    await user.keyboard('{Shift>}{Enter}{/Shift}')

    expect(spy).not.toHaveBeenCalled()
  })

  it('送出的是目前選到的病患 id', async () => {
    const spy = vi.fn().mockResolvedValue(jsonResponse(answer()))
    vi.stubGlobal('fetch', spy)

    const user = userEvent.setup()
    render(<ChatPanel patientId="patient-42" patientName="Amy" />)
    await user.type(screen.getByRole('textbox'), '他在吃什麼藥?')
    await user.keyboard('{Enter}')

    await waitFor(() => expect(spy).toHaveBeenCalled())
    const body = JSON.parse(spy.mock.calls[0][1].body as string) as { patient_id: string }
    expect(body.patient_id).toBe('patient-42')
  })
})
