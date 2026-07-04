import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}

function GateChip({ gate_result, status }) {
  if (status === 'pending') return <span className="status status-pending">pending</span>
  if (status === 'running') return <span className="status status-running">running</span>
  if (status === 'failed')  return <span className="status status-fail">error</span>
  if (!gate_result) return <span style={{ color: 'var(--muted)' }}>—</span>
  return gate_result.passed
    ? <span className="status status-pass">pass</span>
    : <span className="status status-fail">fail</span>
}

export default function AgentDetail() {
  const { agentId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`/dashboard/agents/${agentId}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(setData)
      .catch(e => setError(String(e)))
  }, [agentId])

  if (error) return <p className="empty">Failed to load agent: {error}</p>
  if (!data)  return <p className="loading">Loading…</p>

  return (
    <>
      <div className="page-header">
        <div style={{ color: 'var(--muted)', fontSize: 12, fontFamily: 'var(--mono)', marginBottom: 4 }}>
          <Link to="/">Agents</Link> / {data.name}
        </div>
        <h1 className="page-title">{data.name}</h1>
        {data.description && <p className="page-subtitle">{data.description}</p>}
      </div>

      <div className="section">
        <div className="section-label">Version history</div>
        {data.versions.length === 0 ? (
          <p className="empty">No versions registered.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Model</th>
                  <th>Entrypoint</th>
                  <th>Content hash</th>
                  <th>Registered</th>
                </tr>
              </thead>
              <tbody>
                {data.versions.map(v => (
                  <tr key={v.id}>
                    <td><span className="chip">{v.version_label}</span></td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{v.model_name}</td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)' }}>{v.entrypoint}</td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)' }}>{v.content_hash.slice(0,12)}…</td>
                    <td style={{ color: 'var(--muted)', fontSize: 12 }}>{fmtDate(v.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="section">
        <div className="section-label">Recent runs</div>
        {data.recent_runs.length === 0 ? (
          <p className="empty">No runs yet. Trigger one with <code>agentbench run</code>.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Run ID</th>
                  <th>Triggered by</th>
                  <th>Gate</th>
                  <th>Reason</th>
                  <th>Completed</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_runs.map(run => (
                  <tr key={run.id}>
                    <td>
                      <Link to={`/runs/${run.id}`} style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>
                        {run.id.slice(0,8)}…
                      </Link>
                    </td>
                    <td>
                      <span className="chip">{run.triggered_by}</span>
                    </td>
                    <td>
                      <GateChip gate_result={run.gate_result} status={run.status} />
                    </td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--fail)' }}>
                      {run.gate_result && !run.gate_result.passed
                        ? run.gate_result.reasons.join('; ')
                        : ''}
                    </td>
                    <td style={{ color: 'var(--muted)', fontSize: 12 }}>{fmtDate(run.completed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}