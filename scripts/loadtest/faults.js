// 故障注入用的 k6 腳本:一邊打爆 /api/chat,一邊量 /api/health 的延遲。
//
// **這是 Phase 3 那個宣稱的證據**:「provider 掛掉時 threadpool 不會被佔滿,
// 健康檢查仍然排得進去」。那句話原本只有單元測試支持——而單元測試不會有
// 40 個 threadpool slot 被卡死的請求佔滿的情境。
//
// 兩個 scenario 同時跑:
//   chat_load    - 固定併發打 /api/chat(受注入的故障影響)
//   health_probe - 固定速率打 /api/health(不受守門保護,理論上不該被拖慢)
//
// 分開的 trend metric 讓兩者的延遲不會混在一起——用同一個 http_req_duration
// 的話,health 的數字會被 chat 的稀釋掉,什麼都看不出來。

import http from 'k6/http';
import { Trend, Rate } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL;
const PATIENT_ID = __ENV.PATIENT_ID;
const SUMMARY_OUT = __ENV.SUMMARY_OUT;
const DURATION = __ENV.DURATION;

const chatDuration = new Trend('chat_duration', true);
const healthDuration = new Trend('health_duration', true);
const chatRefused = new Rate('chat_refused');
const chatFailed = new Rate('chat_failed');

export const options = {
  scenarios: {
    chat_load: {
      executor: 'constant-vus',
      vus: Number(__ENV.CHAT_VUS),
      duration: DURATION,
      exec: 'chat',
    },
    health_probe: {
      // constant-arrival-rate:不論服務多慢都維持固定發送速率。
      // 用 constant-vus 的話,chat 拖慢時 health 的發送速率也會跟著掉,
      // 量到的就不是「health 有沒有被拖慢」而是「我們有沒有少打幾次」。
      executor: 'constant-arrival-rate',
      rate: 5,
      timeUnit: '1s',
      duration: DURATION,
      preAllocatedVUs: 10,
      maxVUs: 50,
      exec: 'health',
    },
  },
  thresholds: {},
  summaryTrendStats: ['min', 'med', 'avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: false,
};

export function chat() {
  const res = http.post(
    `${BASE_URL}/api/chat`,
    JSON.stringify({ patient_id: PATIENT_ID, question: '這位病患目前在吃什麼藥？' }),
    { headers: { 'Content-Type': 'application/json' }, tags: { kind: 'chat' } },
  );
  chatDuration.add(res.timings.duration);
  chatFailed.add(res.status !== 200);
  if (res.status === 200) {
    try {
      chatRefused.add(JSON.parse(res.body).refused === true);
    } catch {
      chatRefused.add(false);
    }
  }
}

export function health() {
  const res = http.get(`${BASE_URL}/api/health`, { tags: { kind: 'health' } });
  healthDuration.add(res.timings.duration);
}

export function handleSummary(data) {
  return { stdout: '', [SUMMARY_OUT]: JSON.stringify(data) };
}
