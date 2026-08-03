import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { StatusBar } from './StatusBar'
import type { HealthInfo } from '../types'

function health(overrides: Partial<HealthInfo> = {}): HealthInfo {
  return {
    status: 'ok',
    provider: 'gemini',
    model_id: 'gemini-3.1-flash-lite',
    demo_mode: false,
    patient_count: 100,
    auth_required: false,
    api_key_count: 0,
    rate_limit_per_minute: 20,
    budget_limit_usd: 1.0,
    budget_spent_usd_today: 0.0005,
    budget_counting_since: '2026-07-26T13:06:12+00:00',
    ...overrides,
  }
}

/**
 * 這一組測的是**這個專案最容易靜默出錯的那件事**。
 *
 * 2026-07-26 首次部署到 HF Space 時,secret 設定順序錯誤讓容器拿不到金鑰,
 * 服務依設計退回 mock provider。整個系統沒有任何一處失敗——沒有例外、
 * 沒有紅字、問答照樣答得出東西,只是那個 agent 是假的。
 *
 * 唯一分辨得出來的地方,一個是 /api/health 的 provider 欄位,另一個就是這個
 * 狀態列。**優雅降級的本質是讓失敗不像失敗**,所以那個「像不像」必須有測試守著。
 */
describe('StatusBar 的降級揭露', () => {
  it('真實模式明說連上了哪個模型', () => {
    render(<StatusBar health={health()} onApiKeyChange={vi.fn()} />)

    expect(screen.getByText('已連線真實 AI 模型')).toBeTruthy()
    expect(screen.getByText(/gemini-3\.1-flash-lite/)).toBeTruthy()
  })

  it('demo 模式明說回答是模擬的,不能只是不提', () => {
    render(<StatusBar health={health({ demo_mode: true })} onApiKeyChange={vi.fn()} />)

    expect(screen.getByText('示範模式')).toBeTruthy()
    expect(screen.getByText(/預先設定的模擬資料/)).toBeTruthy()
  })

  it('兩種模式的文案互斥——不會同時出現', () => {
    const { unmount } = render(<StatusBar health={health()} onApiKeyChange={vi.fn()} />)
    expect(screen.queryByText('示範模式')).toBeNull()
    unmount()

    render(<StatusBar health={health({ demo_mode: true })} onApiKeyChange={vi.fn()} />)
    expect(screen.queryByText('已連線真實 AI 模型')).toBeNull()
  })

  it('demo 模式不顯示用量——那個數字在 mock 下沒有意義', () => {
    render(<StatusBar health={health({ demo_mode: true })} onApiKeyChange={vi.fn()} />)

    expect(screen.queryByText(/今日用量/)).toBeNull()
  })

  it('真實模式顯示用量與上限,讓人知道還剩多少', () => {
    render(<StatusBar health={health()} onApiKeyChange={vi.fn()} />)

    expect(screen.getByText(/今日用量/)).toBeTruthy()
    expect(screen.getByText(/US\$1\.00/)).toBeTruthy()
  })

  it('health 還沒讀到時不渲染狀態面板,也不會炸', () => {
    render(<StatusBar health={null} onApiKeyChange={vi.fn()} />)

    expect(screen.queryByText('示範模式')).toBeNull()
    expect(screen.queryByText('已連線真實 AI 模型')).toBeNull()
    // 標題仍在,頁面不是空白
    expect(screen.getByText('FHIR Care Copilot')).toBeTruthy()
  })
})

describe('StatusBar 的 API key 控制項', () => {
  it('揭露金鑰只在頁面記憶體中,會隨請求傳送並在頁面結束後清除', () => {
    render(<StatusBar health={health({ auth_required: true })} onApiKeyChange={vi.fn()} />)

    expect(screen.getByText(/目前頁面的記憶體/)).toBeTruthy()
    expect(screen.getByText(/隨 API 請求傳給此服務/)).toBeTruthy()
    expect(screen.getByText(/重新整理或關閉頁面後會清除/)).toBeTruthy()
  })

  it('伺服器沒設任何金鑰也不要求認證時不顯示——那只是雜訊', () => {
    render(
      <StatusBar
        health={health({ auth_required: false, api_key_count: 0 })}
        onApiKeyChange={vi.fn()}
      />,
    )

    expect(screen.queryByRole('button', { name: '儲存' })).toBeNull()
  })

  it('伺服器要求認證時顯示出來,而且自動展開', () => {
    render(<StatusBar health={health({ auth_required: true })} onApiKeyChange={vi.fn()} />)

    // 要求認證且本機還沒設金鑰 → 自動展開。收合著的話使用者要先被擋一次、
    // 再自己找到摺疊區塊才知道要做什麼,那是猜測成本。
    expect(screen.getByRole('button', { name: '儲存' })).toBeTruthy()
    expect(screen.getByText('此服務目前要求認證')).toBeTruthy()
  })

  it('伺服器設了金鑰但不強制認證時也顯示——使用者可能想自己帶 key', () => {
    render(
      <StatusBar
        health={health({ auth_required: false, api_key_count: 2 })}
        onApiKeyChange={vi.fn()}
      />,
    )

    expect(screen.getByRole('button', { name: '儲存' })).toBeTruthy()
  })
})
