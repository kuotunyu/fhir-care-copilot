import type { AgentResponse } from '../types'

export function StatusBadge({ response }: { response: AgentResponse }) {
  return (
    <div className="status-badge mono" title={`模型:${response.model}`}>
      <span>{response.model}</span>
      <span className="status-badge__divider" aria-hidden="true">
        ·
      </span>
      <span>{response.latency_ms} ms</span>
      <span className="status-badge__divider" aria-hidden="true">
        ·
      </span>
      <span>
        {response.input_tokens}→{response.output_tokens} tok
      </span>
      <span className="status-badge__divider" aria-hidden="true">
        ·
      </span>
      <span>US${response.estimated_cost_usd.toFixed(5)}</span>
    </div>
  )
}
