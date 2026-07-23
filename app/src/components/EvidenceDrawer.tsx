import type { Evidence } from '../types'

export function EvidenceDrawer({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) return null

  return (
    <details className="evidence-drawer">
      <summary>
        證據抽屜
        <span className="evidence-drawer__count mono">{evidence.length}</span>
      </summary>
      <ul className="evidence-drawer__list">
        {evidence.map((e, i) => (
          <li key={i} className="evidence-item">
            <span className="evidence-item__resource mono">
              {e.resource_type}/{e.resource_id.slice(0, 8)}
            </span>
            {e.field && (
              <span className="evidence-item__field">
                {e.field}
                {e.value ? ` = ${e.value}` : ''}
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  )
}
