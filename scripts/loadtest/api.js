// k6 腳本:對單一端點以固定併發跑固定時間,輸出 summary JSON。
//
// 由 scripts/run_loadtest.py 驅動,所有參數走 __ENV 傳進來——這個檔案本身
// 不做任何決策,參數的權威來源是 configs/ops.yaml。
//
// 量到的是「服務層」:FastAPI + 路由 + 工具執行 + FHIR store。
// /api/chat 用的是 mock provider 加固定延遲,**不含真實 LLM 供應商的延遲**。

import http from 'k6/http';
import { check } from 'k6';

const BASE_URL = __ENV.BASE_URL;
const TARGET = __ENV.TARGET;
const PATIENT_ID = __ENV.PATIENT_ID;
const SUMMARY_OUT = __ENV.SUMMARY_OUT;

export const options = {
  vus: Number(__ENV.VUS),
  duration: __ENV.DURATION,
  // 基線量測刻意不設 threshold:這一步的目的是「記錄現況是什麼」,
  // 不是「判斷現況合不合格」。合格線要等有了對照組才談得上。
  thresholds: {},
  summaryTrendStats: ['min', 'med', 'avg', 'p(50)', 'p(90)', 'p(95)', 'p(99)', 'max'],
  // 每個 VU 自己建連線,不要讓連線重用把 server 端成本藏起來
  noConnectionReuse: false,
  discardResponseBodies: false,
};

const JSON_HEADERS = { 'Content-Type': 'application/json' };

function request() {
  switch (TARGET) {
    case 'health':
      return http.get(`${BASE_URL}/api/health`);
    case 'patients':
      return http.get(`${BASE_URL}/api/patients`);
    case 'summary':
      return http.get(`${BASE_URL}/api/patients/${PATIENT_ID}/summary`);
    case 'chat':
      return http.post(
        `${BASE_URL}/api/chat`,
        JSON.stringify({ patient_id: PATIENT_ID, question: '這位病患目前在吃什麼藥？' }),
        { headers: JSON_HEADERS },
      );
    default:
      throw new Error(`unknown TARGET: ${TARGET}`);
  }
}

export default function () {
  const res = request();
  check(res, { 'status is 200': (r) => r.status === 200 });
}

export function handleSummary(data) {
  // stdout 留空:runner 只讀 JSON,終端機不需要 k6 的預設表格
  return { stdout: '', [SUMMARY_OUT]: JSON.stringify(data) };
}
