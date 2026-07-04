import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

function gateStatus(run) {
  if (!run) return { label: '—', cls: '' }
  if (run.status === 'pending') return { label: 'pending', cls: 'status-pending' }
  if (run.status === 'running') return { label: 'running', cls: 'status-running' }
  if (run.status === 'failed') return { label: 'error', cls: 'status-fail' }
  if (run.gate_passed === true)  return { label: 'pass', cls: 'status-pass' }
  if (run.gate_passed === false) return { label: 'fail', cls: 'status-fail' }
  return { label: '—', cls: '' }
}

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}

export default function AgentsList() {
  const [agents, setAgents] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch('/dashboard/agents')
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(setAgents)
      .catch(e => setError(String(e)))
  }, [])

  if (error) return <p className="empty">Failed to load agents: {error}</p>
  if (!agents) return <p className="loading">Loading agents…</p>

  return (
    <>
      <div className="page-header">
        <h1 className="page-title">Agents</h1>
        <p className="page-subtitle">All registered agents and their latest eval status.</p>
      </div>

      {agents.length === 0 ? (
        <p className="empty">No agents registered yet. Run <code>agentbench init</code> to get started.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Agent</th>
                <th>Latest version</th>
                <th>Last run</th>
                <th>Gate</th>
                <th>Completed</th>
              </tr>
            </thead>
            <tbody>
              {agents.map(agent => {
                const gs = gateStatus(agent.latest_run)
                return (
                  <tr key={agent.id}>
                    <td>
                      <Link to={`/agents/${agent.id}`} style={{ fontFamily: 'var(--mono)', fontWeight: 600 }}>
                        {agent.name}
                      </Link>
                      {agent.description && (
                        <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 2 }}>{agent.description}</div>
                      )}
                    </td>
                    <td>
                      {agent.latest_version_label
                        ? <span className="chip">{agent.latest_version_label}</span>
                        : <span style={{ color: 'var(--muted)' }}>—</span>}
                    </td>
                    <td>
                      {agent.latest_run
                        ? <Link to={`/runs/${agent.latest_run.id}`} style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>
                            {agent.latest_run.id.slice(0, 8)}…
                          </Link>
                        : <span style={{ color: 'var(--muted)' }}>—</span>}
                    </td>
                    <td>
                      {gs.label !== '—'
                        ? <span className={`status ${gs.cls}`}>{gs.label}</span>
                        : <span style={{ color: 'var(--muted)' }}>—</span>}
                    </td>
                    <td style={{ color: 'var(--muted)', fontSize: 12 }}>
                      {fmtDate(agent.latest_run?.completed_at)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}