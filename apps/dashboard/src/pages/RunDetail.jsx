import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
  })
}

function fmtMs(ms) {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function fmtCost(usd) {
  return usd === 0 ? '$0.00' : `$${usd.toFixed(6)}`
}

function ScorerDetail({ scorerResults }) {
  const entries = Object.entries(scorerResults)
  return (
    <div className="scorer-row">
      {entries.map(([scorer, result]) => (
        <div key={scorer} className={`scorer-item ${result.passed ? 'pass-item' : 'fail-item'}`}>
          {result.passed ? '✓' : '✗'} {scorer.replace('Scorer', '')}: {result.detail}
        </div>
      ))}
    </div>
  )
}

export default function RunDetail() {
  const { runId } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`/dashboard/runs/${runId}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.statusText))
      .then(setData)
      .catch(e => setError(String(e)))
  }, [runId])

  if (error) return <p className="empty">Failed to load run: {error}</p>
  if (!data)  return <p className="loading">Loading…</p>

  const gate = data.gate_result
  const isPending = data.status === 'pending' || data.status === 'running'

  return (
    <>
      <div style={{ color: 'var(--muted)', fontSize: 12, fontFamily: 'var(--mono)', marginBottom: 16 }}>
        <Link to="/">Agents</Link> / run / {runId.slice(0, 8)}…
      </div>

      {/* Signature element: full-width gate verdict band */}
      {!isPending && gate && (
        <div className={`gate-banner ${gate.passed ? 'pass' : 'fail'}`}>
          <div className={`gate-verdict ${gate.passed ? 'pass' : 'fail'}`}>
            {gate.passed ? 'GATE PASSED' : 'GATE FAILED'}
          </div>
          {!gate.passed && gate.reasons.length > 0 && (
            <ul className="gate-reasons">
              {gate.reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
        </div>
      )}

      {isPending && (
        <div className="gate-banner" style={{ background: 'rgba(56,139,253,.08)', border: '1px solid rgba(56,139,253,.2)' }}>
          <div className="gate-verdict" style={{ color: 'var(--accent)' }}>
            {data.status.toUpperCase()}
          </div>
          <div style={{ color: 'var(--muted)', fontSize: 12, fontFamily: 'var(--mono)' }}>
            Evaluation in progress…
          </div>
        </div>
      )}

      <div style={{ display: 'flex', gap: 32, fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
        <span>triggered: <span style={{ color: 'var(--text)' }}>{data.triggered_by}</span></span>
        <span>started: <span style={{ color: 'var(--text)' }}>{fmtDate(data.started_at)}</span></span>
        <span>completed: <span style={{ color: 'var(--text)' }}>{fmtDate(data.completed_at)}</span></span>
      </div>

      <div className="section">
        <div className="section-label">Per-case results</div>
        {data.case_results.length === 0 ? (
          <p className="empty">No case results yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Result</th>
                  <th>Latency</th>
                  <th>Cost</th>
                  <th>Scorer detail</th>
                </tr>
              </thead>
              <tbody>
                {data.case_results.map(cr => (
                  <tr key={cr.case_id}>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{cr.case_key}</td>
                    <td>
                      <span className={`status ${cr.passed ? 'status-pass' : 'status-fail'}`}>
                        {cr.passed ? 'pass' : 'fail'}
                      </span>
                    </td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{fmtMs(cr.latency_ms)}</td>
                    <td style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{fmtCost(cr.cost_usd)}</td>
                    <td><ScorerDetail scorerResults={cr.scorer_results} /></td>
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