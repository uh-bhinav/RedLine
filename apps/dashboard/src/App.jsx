import { Routes, Route, Link } from 'react-router-dom'
import AgentsList from './pages/AgentsList'
import AgentDetail from './pages/AgentDetail'
import RunDetail from './pages/RunDetail'

export default function App() {
  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" style={{ textDecoration: 'none' }}>
          <span className="topbar-logo">Red<span>Line</span></span>
        </Link>
        <span style={{ color: 'var(--muted)', fontSize: 12, fontFamily: 'var(--mono)' }}>
          agent reliability
        </span>
      </header>
      <main className="page">
        <Routes>
          <Route path="/" element={<AgentsList />} />
          <Route path="/agents/:agentId" element={<AgentDetail />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
        </Routes>
      </main>
    </div>
  )
}