import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

// jsdom 沒有實作 Element.prototype.scrollTo(它不做版面配置,所以捲動沒有意義),
// 而 ChatPanel 送出後會把對話捲到底。不補這個 stub 的話,每個送出測試都會噴一個
// uncaught TypeError——測試仍然「過」,但輸出滿是紅字,久了就沒人看了。
//
// **誠實記錄:補上 stub 等於「自動捲到底」這個行為在單元測試裡沒有被驗證。**
// 它是版面行為,本來就該在真實瀏覽器裡看(這個專案用 Playwright 對線上頁面做過)。
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {}
}

// 不開 vitest 的 globals:每個測試檔自己 import describe/it/expect。
// 代價是多幾行 import,換到的是 tsc 看得懂這些符號從哪來,而且不會有
// 「測試環境才存在的全域變數」這種只在某一邊成立的東西。
afterEach(() => {
  cleanup()
  localStorage.clear()
})
