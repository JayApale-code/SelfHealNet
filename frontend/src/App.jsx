import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { loadDashboard, getSdnStatus, checkBackendHealth, loginUser, logoutUser, registerUser, getProfile, forgotPassword, verifyResetOtp, resetPassword, saveToken, getLoginHistory, getSettings, updateSettings, updateProfile, getAlerts, getNotifications, getPredictions, getHistoricalMetrics, getRecoveryStatus, getTopology, getNetworkInfo } from './services/api'

const unavailable = 'Data Unavailable'

function formatDisplayValue(value, unit = '') {
  if (value === null || value === undefined || value === '') return unavailable
  if (typeof value === 'string') return value
  const numberValue = Number(value)
  if (Number.isFinite(numberValue)) {
    const rounded = Number.isInteger(numberValue) ? numberValue : Number(numberValue.toFixed(2))
    return `${rounded}${unit && unit !== '%' ? ` ${unit}` : ''}`
  }
  return String(value)
}

function isFreshMetric(timestamp, now, freshnessSeconds) {
  if (!timestamp) return false
  const normalizedTimestamp = /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp)
    ? timestamp
    : `${timestamp}Z`
  const measuredAt = Date.parse(normalizedTimestamp)
  const age = now - measuredAt
  return Number.isFinite(measuredAt) && age >= 0 && age <= freshnessSeconds * 1000
}

function MetricCard({ label, value, unit = '', detail = '', trend = '', tone = 'cyan', bars = [] }) {
  const display = value === null || value === undefined || value === '' ? unavailable : value
  const numericValues = bars.map(point => point.value)
  const minimum = numericValues.length ? Math.min(...numericValues) : 0
  const maximum = numericValues.length ? Math.max(...numericValues) : 0
  const range = maximum - minimum || 1
  const chartPoints = bars.map((point, index) => ({
    ...point,
    x: bars.length === 1 ? 50 : (index / (bars.length - 1)) * 100,
    y: 27 - ((point.value - minimum) / range) * 20,
  }))
  const chartLine = chartPoints.map(point => `${point.x},${point.y}`).join(' ')
  return <article className={`metric-card ${tone}`}>
    <div className="metric-top"><span>{label}</span><span className="metric-trend">{trend}</span></div>
    <div className="metric-value">{display}<small>{display === unavailable ? '' : unit}</small></div>
    {detail && <p className="metric-detail">{detail}</p>}
    {chartPoints.length ? <svg className="sparkline" viewBox="0 0 100 32" preserveAspectRatio="none" role="img" aria-label={`Recent ${label.toLowerCase()} measurements, range ${minimum} to ${maximum}${unit ? ` ${unit}` : ''}`}>
      <line className="sparkline-grid" x1="0" y1="27" x2="100" y2="27" />
      {chartPoints.length > 1 && <polyline className="sparkline-line" points={chartLine} />}
      {chartPoints.map((point, index) => <circle className="sparkline-point" key={`${point.timestamp}-${index}`} cx={point.x} cy={point.y} r={chartPoints.length === 1 ? 2.5 : 1.8}>
        <title>{`${point.value}${unit ? ` ${unit}` : ''}${point.timestamp ? ` · ${new Date(point.timestamp).toLocaleString()}` : ''}`}</title>
      </circle>)}
    </svg> : <div className="sparkline-empty" role="status">{unavailable}</div>}
  </article>
}

function statusTone(status) {
  const value = String(status).trim().toLowerCase()
  if (/\b(not available|unavailable|not connected|disconnected|inactive|unknown|not loaded|not active|not healthy|data unavailable)\b/.test(value)) return 'neutral'
  if (/\b(error|failed|failure|offline|critical|high)\b/.test(value)) return 'error'
  if (/\b(degraded|warning|medium)\b/.test(value)) return 'warning'
  if (/\b(normal|success|succeeded|healthy|connected|active|loaded|live|inferred|resolved|passed|low)\b/.test(value)) return 'success'
  if (/\b(loading|processing|pending|checking|starting|waiting|queued)\b/.test(value)) return 'loading'
  return 'neutral'
}

function StatusBadge({ children, inProgress = false }) {
  const tone = statusTone(children)
  return <span className={`badge badge-${tone}`} role="status">
    {inProgress && tone === 'loading' && <span className="badge-spinner" aria-hidden="true" />}
    {children}
  </span>
}

function ToastViewport({ toasts, onDismiss }) {
  return <div className="toast-viewport" aria-label="Notifications" aria-live="polite" aria-atomic="false">
    {toasts.map(toast => <Toast key={toast.id} toast={toast} onDismiss={onDismiss} />)}
  </div>
}

function Toast({ toast, onDismiss }) {
  useEffect(() => {
    const timeout = window.setTimeout(() => onDismiss(toast.id), 3600)
    return () => window.clearTimeout(timeout)
  }, [toast.id, onDismiss])

  const icons = { success: '✓', error: '!', warning: '!', info: 'i' }
  return <div className={`toast toast-${toast.type}`} role={toast.type === 'error' ? 'alert' : 'status'}>
    <span className="toast-icon" aria-hidden="true">{icons[toast.type] || icons.info}</span>
    <p>{toast.message}</p>
    <button className="toast-close" type="button" onClick={() => onDismiss(toast.id)} aria-label="Dismiss notification">×</button>
  </div>
}

function Topology({ topology, fault }) {
  const nodes = (topology?.nodes || []).map(node => (
    typeof node === 'string' ? node : String(node?.id ?? node?.dpid ?? '')
  )).filter(Boolean)
  const links = (topology?.links || []).map(link => (
    Array.isArray(link) ? link : [link?.source, link?.target]
  )).filter(link => link[0] && link[1])
  const positions = {
    'web-01': [10, 25], 'web-02': [10, 70], 'edge-sw-01': [34, 48],
    'core-rtr-01': [63, 27], 'core-rtr-02': [63, 72], 'db-01': [88, 27],
  }

  if (!nodes.length) {
    return <div className="topology-canvas"><div className="topology-grid" /><div className="path-label"><span className="pulse-dot" /> Topology unavailable</div></div>
  }

  return <div className="topology-canvas">
    <div className="topology-grid" />
    {links.map(([from, to], index) => {
      const a = positions[from] || [20 + index * 8, 50]
      const b = positions[to] || [70, 50]
      const length = Math.hypot((b[0] - a[0]) * 1.8, b[1] - a[1])
      const angle = Math.atan2(b[1] - a[1], (b[0] - a[0]) * 1.8) * 180 / Math.PI
      return <div className="topology-link" key={`${from}-${to}`} style={{ left: `${a[0]}%`, top: `${a[1]}%`, width: `${length}%`, transform: `rotate(${angle}deg)` }} />
    })}
    {nodes.map((node, index) => {
      const [left, top] = positions[node] || [12 + (index % 4) * 22, 20 + (index % 2) * 55]
      const isFault = node === fault?.affected_component
      const kind = node.includes('web') || node.includes('db') ? 'host' : 'switch'
      return <div className={`topology-node ${kind} ${isFault ? 'is-fault' : ''}`} key={node} style={{ left: `${left}%`, top: `${top}%` }}>
        <span className="node-icon">{kind === 'host' ? 'H' : 'S'}</span><b>{node}</b><em>{isFault ? 'affected' : kind}</em>
      </div>
    })}
    <div className="path-label"><span className="pulse-dot" /> Controller topology · {links.length} reported links</div>
  </div>
}

function SdnControllerPanel({ snapshot, fault }) {
  const switches = snapshot?.switches || []
  const connected = snapshot?.status === 'CONNECTED'

  return <div className="sdn-controller-content">
    <div className="sdn-controller-summary">
      <StatusBadge>{snapshot?.connection_state || snapshot?.status || 'NOT_CONFIGURED'}</StatusBadge>
      <span>{snapshot?.controller_url || (snapshot?.status === 'SIMULATED' ? 'In-process simulation' : 'No REST API endpoint configured')}</span>
      <small>Last checked: {snapshot?.last_check_at ? new Date(snapshot.last_check_at).toLocaleString() : unavailable}</small>
    </div>
    {snapshot?.message && <p className={`sdn-controller-message ${connected && !snapshot?.reconnection_pending ? 'is-info' : 'is-warning'}`} role="status">{snapshot.message}</p>}
    {snapshot?.error && <p className={`sdn-controller-message ${connected ? 'is-info' : ''}`} role="status">{snapshot.error}</p>}
    {(snapshot?.partial_errors || []).map((item, index) => <p className="sdn-controller-message is-warning" key={`${item.endpoint}-${index}`}>
      {item.endpoint}: {item.error}
    </p>)}
    {connected && snapshot?.topology?.nodes?.length > 0 && <Topology topology={snapshot.topology} fault={fault} />}
    {connected && switches.length > 0 && <div className="sdn-switch-list">
      {switches.map(sw => <article className="sdn-switch" key={sw.dpid}>
        <div className="sdn-switch-heading">
          <strong>Switch {sw.dpid}</strong>
          <span>{sw.ports?.length ?? 0} reported ports · {sw.flow_count ?? 'Flow stats unavailable'} flows</span>
        </div>
        {sw.ports?.length > 0 && <div className="sdn-stat-list">
          {sw.ports.map((port, index) => <div className="sdn-stat-row" key={`${sw.dpid}-port-${port.port_no ?? index}`}>
            <b>Port {port.port_no ?? 'unknown'}{port.name ? ` · ${port.name}` : ''}</b>
            <span>RX {port.rx_bytes ?? 'unavailable'} B · TX {port.tx_bytes ?? 'unavailable'} B</span>
            <small className="sdn-port-state">{port.available ? 'AVAILABLE' : 'DESCRIPTOR UNAVAILABLE'} · ADMIN {port.admin_state || 'UNKNOWN'} · LINK {port.link_state || 'UNKNOWN'} · OPER {port.operational_state || 'UNKNOWN'} · {port.forwarding_state || 'FORWARDING UNKNOWN'} · TRAFFIC {port.traffic_state || 'UNKNOWN'}</small>
          </div>)}
        </div>}
        {sw.flows?.length > 0 && <div className="sdn-stat-list">
          {sw.flows.slice(0, 5).map((flow, index) => <div className="sdn-stat-row" key={`${sw.dpid}-flow-${index}`}>
            <b>Flow {flow.priority ?? index + 1}</b>
            <span>{flow.packet_count ?? 'unavailable'} packets · {flow.byte_count ?? 'unavailable'} bytes</span>
          </div>)}
          {sw.flows.length > 5 && <small className="sdn-more-flows">Showing 5 of {sw.flows.length} reported flows.</small>}
        </div>}
      </article>)}
    </div>}
    {connected && switches.length === 0 && <div className="sdn-empty-state">
      The Ryu REST API is reachable, but it reports no connected OpenFlow switches. Switch ports, links, and flows are not available.
    </div>}
    {snapshot?.status === 'SIMULATED' && <div className="sdn-empty-state">
      Simulation data is not a real controller connection; switch and flow statistics are unavailable.
    </div>}
  </div>
}

function TrafficFabric({ metrics, interfaceId, controllerStatus }) {
  const trafficTypes = {
    sent: 'throughput_sent_bps',
    received: 'throughput_received_bps',
  }
  const series = Object.fromEntries(Object.entries(trafficTypes).map(([direction, metricType]) => [
    direction,
    metrics
      .filter(metric => metric.metric_type === metricType && Number.isFinite(Number(metric.value)))
      .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp))
      .slice(-20)
      .map(metric => ({
        value: Number(metric.value),
        timestamp: metric.timestamp,
        interfaceId: metric.interface_id,
      })),
  ]))
  const allPoints = [...series.sent, ...series.received]
  const latestFor = points => points.at(-1) || null
  const maximum = Math.max(1, ...allPoints.map(point => point.value))
  const chartCoordinates = points => points.map((point, index) => ({
    ...point,
    x: points.length === 1 ? 300 : (index / (points.length - 1)) * 600,
    y: 116 - (point.value / maximum) * 96,
  }))
  const chartPath = points => chartCoordinates(points)
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x},${point.y}`)
    .join(' ')
  const latestTimestamp = allPoints
    .map(point => point.timestamp)
    .filter(Boolean)
    .sort((left, right) => Date.parse(right) - Date.parse(left))[0]
  const selectedInterface = interfaceId
    || latestFor(series.sent)?.interfaceId
    || latestFor(series.received)?.interfaceId

  return <div className="traffic-fabric">
    <div className="traffic-meta">
      <span>HOST INTERFACE TELEMETRY</span>
      <b>{selectedInterface || 'Interface unavailable'}</b>
      <small>Measured interface rates · MiB/s · {latestTimestamp ? new Date(latestTimestamp).toLocaleString() : 'no recent measurement'}</small>
    </div>
    {allPoints.length ? <>
      <div className="traffic-readouts">
        <div><span>UPLOAD</span><b>{latestFor(series.sent) ? `${(latestFor(series.sent).value / (1024 ** 2)).toFixed(2)} MiB/s` : unavailable}</b></div>
        <div><span>DOWNLOAD</span><b>{latestFor(series.received) ? `${(latestFor(series.received).value / (1024 ** 2)).toFixed(2)} MiB/s` : unavailable}</b></div>
      </div>
      <svg className="traffic-chart" viewBox="0 0 600 140" preserveAspectRatio="none" role="img" aria-label="Recent measured host interface upload and download rates in mebibytes per second">
        {[20, 68, 116].map(y => <line key={y} className="traffic-grid-line" x1="0" y1={y} x2="600" y2={y} />)}
        {series.sent.length > 1 && <path className="traffic-line traffic-line-sent" d={chartPath(series.sent)} />}
        {series.received.length > 1 && <path className="traffic-line traffic-line-received" d={chartPath(series.received)} />}
        {[
          ...chartCoordinates(series.sent).map(point => ({ ...point, direction: 'sent' })),
          ...chartCoordinates(series.received).map(point => ({ ...point, direction: 'received' })),
        ].map((point, index) => <circle
          className={`traffic-point traffic-point-${point.direction}`}
          key={`${point.direction}-${point.timestamp}-${index}`}
          cx={point.x}
          cy={point.y}
          r="3"
        ><title>{`${(point.value / (1024 ** 2)).toFixed(3)} MiB/s · ${new Date(point.timestamp).toLocaleString()}`}</title></circle>)}
      </svg>
      <div className="traffic-legend"><span><i className="traffic-legend-sent" /> Upload</span><span><i className="traffic-legend-received" /> Download</span></div>
      <p className="traffic-disclaimer">Interface byte-counter rates only; these are not verified SDN flows. Controller: {controllerStatus}.</p>
    </> : <div className="traffic-empty" role="status">
      <strong>Interface traffic data unavailable</strong>
      <span>No fresh sent/received interface-rate measurements were returned by the backend.</span>
      <span>SDN topology and flow data require a connected controller and configured flow source; controller: {controllerStatus}.</span>
    </div>}
  </div>
}

function AuthScreen({ mode, setMode, onSubmit, loading, setLoading, message, setMessage, onNotify }) {
  const [form, setForm] = useState({
    full_name: '',
    username: '',
    email: '',
    mobile_number: '',
    password: '',
    username_or_email: '',
  })
  const [resetEmail, setResetEmail] = useState('')
  const [otp, setOtp] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  const isLogin = mode === 'login'
  const isRegister = mode === 'register'

  const startPasswordReset = async event => {
    event.preventDefault()
    setLoading(true)
    setMessage('')
    try {
      const result = await forgotPassword(resetEmail)
      setMode('verify-otp')
      setMessage(result.message)
      onNotify('success', result.message || 'Password reset code request accepted.')
    } catch (error) {
      setMessage(error.message)
      onNotify('error', error.message || 'Could not request a password reset code.')
    } finally {
      setLoading(false)
    }
  }

  const verifyPasswordResetOtp = async event => {
    event.preventDefault()
    setLoading(true)
    setMessage('')
    try {
      const result = await verifyResetOtp({ email: resetEmail, otp })
      setResetToken(result.reset_token)
      setMode('reset-password')
      setMessage(result.message)
      onNotify('success', result.message || 'Reset code verified.')
    } catch (error) {
      setMessage(error.message)
      onNotify('error', error.message || 'Could not verify the reset code.')
    } finally {
      setLoading(false)
    }
  }

  const finishPasswordReset = async event => {
    event.preventDefault()
    setLoading(true)
    setMessage('')
    try {
      const result = await resetPassword({
        token: resetToken,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      setMode('login')
      setMessage(result.message)
      onNotify('success', result.message || 'Password reset successfully.')
      setOtp('')
      setResetToken('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (error) {
      setMessage(error.message)
      onNotify('error', error.message || 'Could not reset the password.')
    } finally {
      setLoading(false)
    }
  }

  if (mode === 'forgot-password') {
    return <div className="auth-shell">
      <h2>Forgot password</h2>
      <p>Request a one-time reset code for your account.</p>
      <form onSubmit={startPasswordReset} style={{ display: 'grid', gap: 12 }}>
        <input type="email" required value={resetEmail} placeholder="Account email" onChange={event => setResetEmail(event.target.value)} />
        <button type="submit" disabled={loading}>{loading ? 'Please wait...' : 'Request code'}</button>
        {message && <div role="status" className="auth-message">{message}</div>}
        <p className="auth-helper">Development mock only: no SMS is sent and no code is shown in this response.</p>
        <button type="button" onClick={() => { setMode('login'); setMessage('') }}>Back to sign in</button>
      </form>
    </div>
  }

  if (mode === 'verify-otp') {
    return <div className="auth-shell">
      <h2>Verify reset code</h2>
      <p>Enter the six-digit code from the configured delivery provider.</p>
      <form onSubmit={verifyPasswordResetOtp} style={{ display: 'grid', gap: 12 }}>
        <input type="email" required value={resetEmail} placeholder="Account email" onChange={event => setResetEmail(event.target.value)} />
        <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={otp} placeholder="Six-digit code" onChange={event => setOtp(event.target.value.replace(/\D/g, '').slice(0, 6))} />
        <button type="submit" disabled={loading}>{loading ? 'Verifying...' : 'Verify code'}</button>
        {message && <div role="status" className="auth-message">{message}</div>}
        <p className="auth-helper">The development mock does not send SMS. A code is available only through an injected test provider.</p>
        <button type="button" onClick={() => { setMode('forgot-password'); setMessage('') }}>Request another code</button>
      </form>
    </div>
  }

  if (mode === 'reset-password') {
    return <div className="auth-shell">
      <h2>Set a new password</h2>
      <p>Your verification code was accepted. Choose a new password.</p>
      <form onSubmit={finishPasswordReset} style={{ display: 'grid', gap: 12 }}>
        <input type="password" minLength={8} maxLength={128} required autoComplete="new-password" value={newPassword} placeholder="New password" onChange={event => setNewPassword(event.target.value)} />
        <input type="password" minLength={8} maxLength={128} required autoComplete="new-password" value={confirmPassword} placeholder="Confirm new password" onChange={event => setConfirmPassword(event.target.value)} />
        <button type="submit" disabled={loading}>{loading ? 'Updating...' : 'Reset password'}</button>
        {message && <div role="status" className="auth-message">{message}</div>}
      </form>
    </div>
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    const payload = isLogin
      ? { username_or_email: form.username_or_email, password: form.password }
      : {
          full_name: form.full_name,
          username: form.username,
          email: form.email,
          mobile_number: form.mobile_number,
          password: form.password,
        }
    await onSubmit(payload)
  }

  return <div className="auth-shell">
    <h2>{isLogin ? 'Sign in' : 'Create account'}</h2>
    <p>{isLogin ? 'Access the protected dashboard' : 'Register with the existing SelfHealNet platform'}</p>
    <form onSubmit={handleSubmit} style={{ display: 'grid', gap: 12 }}>
      {isRegister && <>
        <input value={form.full_name} placeholder="Full name" onChange={e => setForm({ ...form, full_name: e.target.value })} />
        <input value={form.username} placeholder="Username" onChange={e => setForm({ ...form, username: e.target.value })} />
      </>}
      {isRegister && <input type="tel" autoComplete="tel" value={form.mobile_number} placeholder="Mobile number" onChange={e => setForm({ ...form, mobile_number: e.target.value })} />}
      <input type={isLogin ? 'text' : 'email'} value={isLogin ? form.username_or_email : form.email} placeholder={isLogin ? 'Username or email' : 'Email'} onChange={e => setForm({ ...form, username_or_email: isLogin ? e.target.value : form.username_or_email, email: !isLogin ? e.target.value : form.email })} />
      <input type="password" autoComplete={isLogin ? 'current-password' : 'new-password'} value={form.password} placeholder="Password" onChange={e => setForm({ ...form, password: e.target.value })} />
      <button type="submit" disabled={loading}>{loading ? 'Please wait...' : isLogin ? 'Login' : 'Register'}</button>
      {message && <div role="status" className="auth-message">{message}</div>}
    </form>
    <div className="auth-links">
      <button type="button" onClick={() => { setMode(isLogin ? 'register' : 'login'); setMessage('') }}>{isLogin ? 'Need an account?' : 'Already have an account?'}</button>
      {isLogin && <button type="button" onClick={() => { setMode('forgot-password'); setMessage('') }}>Forgot password</button>}
    </div>
  </div>
}

function LoginSuccessModal({ onContinue }) {
  return <div className="login-success-backdrop">
    <section className="login-success-modal" role="dialog" aria-modal="true" aria-labelledby="login-success-title">
      <div className="login-success-icon" aria-hidden="true">
        <svg viewBox="0 0 48 48" focusable="false">
          <circle cx="24" cy="24" r="22" />
          <path d="m14 24 7 7 14-15" />
        </svg>
      </div>
      <h1 id="login-success-title">Login Successful!</h1>
      <p>Welcome to SelfHealNet. You have logged in successfully.</p>
      <button className="login-success-button" onClick={onContinue}>Continue to Dashboard</button>
    </section>
  </div>
}

const pageLinks = [
  ['dashboard', 'Dashboard'], ['monitoring', 'Monitoring'], ['recovery', 'Recovery'],
  ['history', 'History'], ['alerts', 'Alerts'], ['notifications', 'Notifications'],
  ['profile', 'Profile'], ['settings', 'Settings'],
]

function Navigation({ activePage, onNavigate }) {
  return <nav className="app-nav" aria-label="Primary navigation">
    {pageLinks.map(([id, label]) => <button key={id} className={activePage === id ? 'active' : ''} onClick={() => onNavigate(id)}>{label}</button>)}
  </nav>
}

function PageFrame({ profile, connected, activePage, onNavigate, onLogout, children }) {
  return <div className="app-shell"><header className="topbar">
    <div className="brand"><div className="brand-mark"><span /><span /><span /></div><div><strong>SELFHEAL<span>NET</span></strong><small>AUTONOMOUS NETWORK OPERATIONS</small></div></div>
    <Navigation activePage={activePage} onNavigate={onNavigate} />
    <div className="header-status"><span className={`live-indicator ${connected ? 'online' : ''}`} /> {connected ? 'LIVE' : 'API'} <span>{profile?.username || 'Authenticated user'}</span><button className="icon-button" title="Log out" onClick={onLogout}>⎋</button></div>
  </header>{children}</div>
}

function PageTitle({ eyebrow, title, detail }) {
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="subhead">{detail}</p></div></div>
}

function RecordList({ title, items, empty = unavailable, render }) {
  return <section className="panel page-panel"><div className="panel-heading"><h2>{title}</h2><span className="trace-id">{items.length} RECORDS</span></div>{items.length ? items.map(render) : <div className="empty-state">{empty}</div>}</section>
}

function MonitoringPage({ onNotify }) {
  const [metrics, setMetrics] = useState([])
  const [predictions, setPredictions] = useState([])
  const [topology, setTopology] = useState({ nodes: [], links: [] })
  const [networkInfo, setNetworkInfo] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => {
    Promise.all([getHistoricalMetrics(), getPredictions(), getTopology(), getNetworkInfo()])
      .then(([metricData, predictionData, topologyData, info]) => {
        setMetrics(metricData.metrics)
        setPredictions(predictionData.predictions)
        setTopology(topologyData)
        setNetworkInfo(info)
      })
      .catch(loadError => {
        setError(loadError.message)
        onNotify('error', `Monitoring data could not be loaded: ${loadError.message}`)
      })
  }, [onNotify])
  const controllerStatus = networkInfo?.connection_details?.sdn_controller?.status || unavailable
  return <main className="dashboard"><PageTitle eyebrow="OBSERVABILITY / TELEMETRY" title="Monitoring and ML" detail="Live network evidence, topology state, and model predictions." />{error && <div className="panel page-panel">Backend data unavailable: {error}</div>}<div className="status-strip"><span>Controller: {controllerStatus}</span><span>Prediction records: {predictions.length}</span></div><div className="page-grid"><RecordList title="Metric history" items={metrics} empty={error ? `Backend data unavailable: ${error}` : 'No metric history'} render={item => <div className="record-row" key={`${item.timestamp}-${item.metric_type}`}><b>{item.metric_type}</b><span>{item.value} {item.unit || ''}</span><small>{item.node_id || unavailable} · {item.timestamp ? new Date(item.timestamp).toLocaleString() : unavailable}</small></div>} /><RecordList title="Predictions" items={predictions} empty={error ? `Backend data unavailable: ${error}` : 'No prediction records'} render={item => <div className="record-row" key={item.prediction_id || item.timestamp}><b>{item.label}</b><span>{Number.isFinite(Number(item.probability)) ? `${Math.round(item.probability * 100)}%` : unavailable}</span><small>{item.component || unavailable} · {item.timestamp ? new Date(item.timestamp).toLocaleString() : unavailable}</small></div>} /></div></main>
}

function RecoveryPage({ onNotify }) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')
  useEffect(() => { getRecoveryStatus().then(setStatus).catch(loadError => { setError(loadError.message); onNotify('error', `Recovery status could not be loaded: ${loadError.message}`) }) }, [onNotify])
  return <main className="dashboard"><PageTitle eyebrow="CONTROL PLANE / RECOVERY" title="Recovery operations" detail="Only controller-supported actions and verified outcomes are shown." />{error && <div className="panel page-panel">Backend data unavailable: {error}</div>}<section className="panel page-panel"><div className="panel-heading"><h2>Current recovery</h2><StatusBadge>{status?.status || unavailable}</StatusBadge></div>{status?.active_recovery ? <pre className="json-view">{JSON.stringify(status.active_recovery, null, 2)}</pre> : <div className="empty-state">{error ? unavailable : 'No recovery record'}</div>}</section></main>
}

function HistoryPage({ onNotify }) {
  const [items, setItems] = useState([])
  useEffect(() => { getLoginHistory().then(result => setItems(result?.items || [])).catch(error => onNotify('error', `Login history could not be loaded: ${error.message}`)) }, [onNotify])
  return <main className="dashboard"><PageTitle eyebrow="AUDIT / ACCESS" title="Login history" detail="Authenticated access events recorded by the backend." /><RecordList title="Recent sign-ins" items={items} render={item => <div className="record-row" key={item.id}><b>{item.success ? 'Successful login' : 'Failed login'}</b><span>{item.login_at ? new Date(item.login_at).toLocaleString() : unavailable}</span><small>{item.ip_address || unavailable} · {item.user_agent || unavailable}</small></div>} /></main>
}

function AlertsPage({ onNotify }) {
  const [items, setItems] = useState([])
  const [error, setError] = useState('')
  useEffect(() => { getAlerts().then(result => setItems(result.alerts)).catch(loadError => { setError(loadError.message); onNotify('error', `Alerts could not be loaded: ${loadError.message}`) }) }, [onNotify])
  return <main className="dashboard"><PageTitle eyebrow="OPERATIONS / ALERTS" title="Alerts" detail="Backend-persisted operational alerts." />{error && <div className="panel page-panel">Backend data unavailable: {error}</div>}<RecordList title="Alert feed" items={items} empty={error ? `Backend data unavailable: ${error}` : 'No alerts'} render={item => <div className="record-row" key={item.id}><b>{item.alert_type}</b><StatusBadge>{item.severity}</StatusBadge><small>{item.message} · {item.created_at ? new Date(item.created_at).toLocaleString() : unavailable}</small></div>} /></main>
}

function NotificationsPage({ onNotify }) {
  const [items, setItems] = useState([])
  const [error, setError] = useState('')
  useEffect(() => { getNotifications().then(result => setItems(result.notifications)).catch(loadError => { setError(loadError.message); onNotify('error', `Notifications could not be loaded: ${loadError.message}`) }) }, [onNotify])
  return <main className="dashboard"><PageTitle eyebrow="OPERATIONS / INBOX" title="Notifications" detail="User notifications associated with this account." />{error && <div className="panel page-panel">Backend data unavailable: {error}</div>}<RecordList title="Notification feed" items={items} empty={error ? `Backend data unavailable: ${error}` : 'No notifications'} render={item => <div className="record-row" key={item.id}><b>{item.type}</b><StatusBadge>{item.severity}</StatusBadge><small>{item.message} · {item.created_at ? new Date(item.created_at).toLocaleString() : unavailable}</small></div>} /></main>
}

function ProfilePage({ profile, onProfileUpdated, onNotify }) {
  const [form, setForm] = useState({ full_name: profile?.full_name || '', email: profile?.email || '', mobile_number: '' })
  const [message, setMessage] = useState('')
  const submit = async event => { event.preventDefault(); try { const payload = { full_name: form.full_name, email: form.email, ...(form.mobile_number.trim() ? { mobile_number: form.mobile_number.trim() } : {}) }; const result = await updateProfile(payload); onProfileUpdated(result); setForm(current => ({ ...current, mobile_number: '' })); setMessage('Profile updated'); onNotify('success', 'Profile updated successfully.') } catch (error) { setMessage(error.message); onNotify('error', error.message || 'Profile update failed.') } }
  return <main className="dashboard"><PageTitle eyebrow="ACCOUNT / PROFILE" title="Profile" detail="Manage the identity details attached to your account." /><section className="panel page-panel form-panel"><form onSubmit={submit}><label>Username<input value={profile?.username || unavailable} disabled /></label><label>Full name<input value={form.full_name} onChange={event => setForm({ ...form, full_name: event.target.value })} /></label><label>Email<input type="email" value={form.email} onChange={event => setForm({ ...form, email: event.target.value })} /></label><label>Mobile number<input type="tel" autoComplete="tel" placeholder={profile?.mobile_number ? `${profile.mobile_number} (enter a new number to replace)` : 'Add a mobile number'} value={form.mobile_number} onChange={event => setForm({ ...form, mobile_number: event.target.value })} /></label><button className="primary-button">Save profile</button>{message && <p className="form-message">{message}</p>}</form></section></main>
}

function SettingsPage({ onNotify }) {
  const [settings, setSettings] = useState(null)
  const [message, setMessage] = useState('')
  useEffect(() => { getSettings().then(setSettings).catch(error => { setMessage(error.message); onNotify('error', `Settings could not be loaded: ${error.message}`) }) }, [onNotify])
  const save = async event => { event.preventDefault(); try { setSettings(await updateSettings(settings)); setMessage('Settings updated'); onNotify('success', 'Settings updated successfully.') } catch (error) { setMessage(error.message); onNotify('error', error.message || 'Settings update failed.') } }
  if (!settings) return <main className="dashboard"><PageTitle eyebrow="ACCOUNT / SETTINGS" title="Settings" detail="Loading account preferences." /><section className="panel page-panel empty-state">{unavailable}</section></main>
  return <main className="dashboard"><PageTitle eyebrow="ACCOUNT / SETTINGS" title="Settings" detail="Control refresh and notification preferences." /><section className="panel page-panel form-panel"><form onSubmit={save}><label>Refresh interval (seconds)<input type="number" min="5" max="600" value={settings.refresh_interval} onChange={event => setSettings({ ...settings, refresh_interval: Number(event.target.value) })} /></label><label className="check-row"><input type="checkbox" checked={settings.notification_enabled} onChange={event => setSettings({ ...settings, notification_enabled: event.target.checked })} /> Notifications enabled</label><label className="check-row"><input type="checkbox" checked={settings.email_alerts} onChange={event => setSettings({ ...settings, email_alerts: event.target.checked })} /> Email alerts</label><label className="check-row"><input type="checkbox" checked={settings.push_notifications} onChange={event => setSettings({ ...settings, push_notifications: event.target.checked })} /> Push notifications</label><button className="primary-button">Save settings</button>{message && <p className="form-message">{message}</p>}</form></section></main>
}

function App() {
  const [token, setToken] = useState(localStorage.getItem('selfhealnet_token') || '')
  const [loginSuccess, setLoginSuccess] = useState(false)
  const [mode, setMode] = useState('login')
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [profile, setProfile] = useState(null)
  const [data, setData] = useState({ status: null, metrics: [], topology: { nodes: [], links: [] }, faults: [], incidents: [], predictions: [], model: { status: 'not_loaded', version: null }, networkInfo: { monitoring_status: 'NOT CONNECTED' }, recoveryStatus: null })
  const [dashboardError, setDashboardError] = useState('')
  const [dashboardLoaded, setDashboardLoaded] = useState(false)
  const [backendHealth, setBackendHealth] = useState('CHECKING')
  const [filter, setFilter] = useState('ALL')
  const [connected, setConnected] = useState(false)
  const [activePage, setActivePage] = useState('dashboard')
  const [now, setNow] = useState(Date.now())
  const [toasts, setToasts] = useState([])
  const dashboardErrorRef = useRef('')

  const notify = useCallback((type, text) => {
    const messageText = String(text || '').trim()
    if (!messageText) return
    const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`
    setToasts(current => {
      if (current.some(toast => toast.type === type && toast.message === messageText)) return current
      return [...current, { id, type, message: messageText }].slice(-5)
    })
  }, [])

  const dismissToast = useCallback(id => setToasts(current => current.filter(toast => toast.id !== id)), [])

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  const handleAuth = async (payload) => {
    setLoading(true)
    setMessage('')
    setLoginSuccess(false)
    try {
      const result = mode === 'login' ? await loginUser(payload) : await registerUser(payload)
      setToken(result.token)
      saveToken(result.token)
      const isLogin = mode === 'login'
      if (isLogin) {
        setLoginSuccess(true)
        notify('success', 'You logged in successfully!')
      } else {
        notify('success', result.message || 'Account created successfully.')
      }
      try {
        const user = await getProfile()
        setProfile(user)
      } catch (error) {
        notify('error', `Authentication succeeded, but profile loading failed: ${error.message}`)
      }
    } catch (error) {
      setMessage(error.message)
      const authFailureMessage = mode === 'login'
        ? /fetch|network|timeout|connection|server|50[0-9]/i.test(error.message)
          ? `Login failed because the authentication service could not be reached: ${error.message}`
          : 'Login failed. Please check your credentials.'
        : error.message || 'Registration failed.'
      notify('error', authFailureMessage)
    } finally {
      setLoading(false)
    }
  }

  const handleLogout = async () => {
    let logoutConfirmed = false
    try {
      await logoutUser()
      logoutConfirmed = true
    } catch (error) {
      notify('error', `Signed out on this device, but the server could not confirm logout: ${error.message}`)
    } finally {
      saveToken(null)
      setToken('')
      setProfile(null)
      setMessage('Logged out successfully')
      if (logoutConfirmed) notify('success', 'You logged out successfully.')
    }
  }

  useEffect(() => {
    if (!token) return
    getProfile().then(setProfile).catch(error => {
      saveToken(null)
      notify('error', `Authentication could not be verified: ${error.message}`)
    })
  }, [token, notify])

  useEffect(() => {
    if (!token) return
    let active = true
    const refreshDashboard = () => loadDashboard()
      .then(result => {
        if (!active) return
        setData(result)
        setDashboardLoaded(true)
        setDashboardError('')
        dashboardErrorRef.current = ''
      })
      .catch(error => {
        if (!active) return
        setDashboardLoaded(false)
        setDashboardError(error.message)
        if (!dashboardErrorRef.current) notify('error', `Dashboard data could not be refreshed: ${error.message}`)
        dashboardErrorRef.current = error.message
      })
    refreshDashboard()
    const refreshTimer = setInterval(refreshDashboard, 30000)
    return () => {
      active = false
      clearInterval(refreshTimer)
    }
  }, [token])

  useEffect(() => {
    if (!token) return
    let active = true
    const refreshSdnStatus = () => getSdnStatus().then(snapshot => {
      if (!active) return
      setData(current => ({
        ...current,
        sdn: snapshot,
        topology: snapshot?.topology || current.topology,
      }))
    }).catch(() => {})
    refreshSdnStatus()
    const refreshTimer = setInterval(refreshSdnStatus, 5000)
    return () => {
      active = false
      clearInterval(refreshTimer)
    }
  }, [token])

  useEffect(() => {
    let active = true
    const refreshBackendHealth = async () => {
      try {
        const healthy = await checkBackendHealth()
        if (active) setBackendHealth(healthy ? 'HEALTHY' : 'DEGRADED')
      } catch {
        if (active) setBackendHealth('UNAVAILABLE')
      }
    }
    refreshBackendHealth()
    const healthTimer = setInterval(refreshBackendHealth, 15000)
    return () => {
      active = false
      clearInterval(healthTimer)
    }
  }, [])

  useEffect(() => {
    if (!token) return
    const socketUrl = import.meta.env.VITE_WS_URL || `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:8000/api/v1/ws/dashboard`
    let socket
    let refreshTimer
    try {
      socket = new WebSocket(socketUrl)
      socket.onopen = () => {
        socket.send(JSON.stringify({ type: 'authenticate', token }))
      }
      socket.onmessage = event => {
        const update = JSON.parse(event.data)
        if (update.type === 'authenticated') {
          setConnected(true)
          refreshTimer = setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) socket.send('ping')
          }, 30000)
          return
        }
        if (update.network_status || update.recovery_status) {
          setData(current => ({
            ...current,
            status: update.network_status || current.status,
            metrics: Array.isArray(update.live_metrics) ? update.live_metrics : current.metrics,
            faults: Array.isArray(update.active_faults) ? update.active_faults : current.faults,
            recoveryStatus: update.recovery_status || current.recoveryStatus,
            networkInfo: update.network_info || current.networkInfo,
          }))
        }
      }
      socket.onclose = () => setConnected(false)
    } catch {
      setConnected(false)
    }
    return () => {
      clearInterval(refreshTimer)
      socket?.close()
    }
  }, [token])

  const filteredIncidents = useMemo(() => {
    if (!data.incidents.length) return []
    if (filter === 'ALL') return data.incidents
    return data.incidents.filter(item => item.final_status === filter)
  }, [data.incidents, filter])

  if (loginSuccess && token) {
    return <><LoginSuccessModal onContinue={() => {
      setLoginSuccess(false)
      setActivePage('dashboard')
    }} /><ToastViewport toasts={toasts} onDismiss={dismissToast} /></>
  }

  if (!token) {
    return <><AuthScreen mode={mode} setMode={setMode} onSubmit={handleAuth} loading={loading} setLoading={setLoading} message={message} setMessage={setMessage} onNotify={notify} /><ToastViewport toasts={toasts} onDismiss={dismissToast} /></>
  }

  if (activePage !== 'dashboard') {
    const page = {
      monitoring: <MonitoringPage onNotify={notify} />,
      recovery: <RecoveryPage onNotify={notify} />,
      history: <HistoryPage onNotify={notify} />,
      alerts: <AlertsPage onNotify={notify} />,
      notifications: <NotificationsPage onNotify={notify} />,
      profile: <ProfilePage profile={profile} onProfileUpdated={setProfile} onNotify={notify} />,
      settings: <SettingsPage onNotify={notify} />,
    }[activePage]
    return <><PageFrame profile={profile} connected={connected} activePage={activePage} onNavigate={setActivePage} onLogout={handleLogout}>{page}</PageFrame><ToastViewport toasts={toasts} onDismiss={dismissToast} /></>
  }

  const fault = data.faults[0] || null
  const getMetricValue = (types, fallback = null) => {
    const found = data.metrics.find(item => types.includes(item.metric_type) || types.includes(item.metric))
    if (!found) return fallback
    const value = found.value ?? found.metric_value ?? null
    return value === null || value === undefined ? fallback : value
  }

  const getMetricSeries = (types) => {
    return freshMetrics
      .filter(item => types.includes(item.metric_type) || types.includes(item.metric))
      .map(item => ({
        value: Number(item.value ?? item.metric_value ?? NaN),
        timestamp: item.timestamp,
      }))
      .filter(point => Number.isFinite(point.value))
      .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp))
      .slice(-8)
  }

  const networkStatus = data.status?.status || 'unknown'
  const networkInfo = data.networkInfo || {}
  const latestIncident = data.incidents[0] || null
  const latestPrediction = data.predictions[0] || null
  const predictionProbability = latestPrediction?.probability
  const numericPredictionProbability = predictionProbability !== null
    && predictionProbability !== undefined
    && predictionProbability !== ''
    ? Number(predictionProbability)
    : NaN
  const numericPredictionThreshold = Number(data.model?.prediction_threshold)
  const predictionBelowThreshold = Number.isFinite(numericPredictionProbability)
    && Number.isFinite(numericPredictionThreshold)
    && numericPredictionProbability < numericPredictionThreshold
  const predictionConfidence = Number.isFinite(numericPredictionProbability)
    ? Math.min(1, Math.max(0, numericPredictionProbability)) * 360
    : 0
  const recoveryStatus = data.recoveryStatus || {}
  const connection = networkInfo.live_connection || {}
  const connectionDetails = networkInfo.connection_details || {}
  const metricFreshnessSeconds = Number(networkInfo.metric_freshness_seconds) || 90
  const freshMetrics = data.metrics.filter(item =>
    isFreshMetric(item.timestamp, now, metricFreshnessSeconds)
    && (!connectionDetails.interface_id || item.interface_id === connectionDetails.interface_id)
  )
  const monitoringIsFresh = isFreshMetric(
    connectionDetails.last_data_received,
    now,
    metricFreshnessSeconds,
  )
  const latencyIsFresh = isFreshMetric(
    networkInfo.latency_measured_at,
    now,
    metricFreshnessSeconds,
  )
  const uploadIsFresh = isFreshMetric(
    networkInfo.upload_throughput_measured_at,
    now,
    metricFreshnessSeconds,
  )
  const downloadIsFresh = isFreshMetric(
    networkInfo.download_throughput_measured_at,
    now,
    metricFreshnessSeconds,
  )
  const monitoringStatus = monitoringIsFresh
    ? 'LIVE'
    : connectionDetails.interface_id ? 'DATA UNAVAILABLE' : 'NOT CONNECTED'
  const sdnControllerStatus = data.sdn?.status || connectionDetails.sdn_controller?.status || 'NOT_CONFIGURED'
  const modelStatus = data.model?.status === 'loaded' ? `ML model: ${data.model.version || 'ready'}` : 'ML Model Not Available'
  const inference = data.model?.telemetry_inference || {}
  const inferenceStatus = inference.state === 'inferred'
    ? 'ACTIVE · INFERENCE SUCCEEDED'
    : inference.running ? 'WAITING FOR FRESH SAMPLES' : 'INACTIVE'
  const recoveryServiceStatus = recoveryStatus.active_recovery ? 'RECORDED' : 'IDLE'
  const health = networkStatus
  const getFreshMetricValue = (types) => {
    const found = [...freshMetrics].reverse().find(item => types.includes(item.metric_type) || types.includes(item.metric))
    const value = found?.value ?? found?.metric_value ?? null
    return value === null || value === undefined ? null : value
  }
  const latency = getFreshMetricValue(['latency_ms', 'latency'])
  const packetLoss = getFreshMetricValue(['packet_loss_pct', 'packet_loss'])
  const bandwidth = getFreshMetricValue(['bandwidth_utilization_pct', 'bandwidth_usage', 'bandwidth_usage_pct'])
  const traffic = getFreshMetricValue(['throughput_mbps', 'throughput'])
  const cpu = getFreshMetricValue(['cpu_utilization_pct', 'cpu_usage_pct', 'cpu_usage'])
  const memory = data.memory?.status === 'available' ? data.memory.usage_pct : null
  const memoryDetail = data.memory?.status === 'available'
    ? `${(Number(data.memory.used_mb) / 1000).toFixed(2)} GB used of ${(Number(data.memory.total_mb) / 1000).toFixed(2)} GB · ${(Number(data.memory.available_mb) / 1000).toFixed(2)} GB available`
    : data.memory?.reason || 'Recent system memory telemetry unavailable'
  const availability = monitoringIsFresh
    ? 'ONLINE'
    : connection.status === 'CONNECTED' ? 'UNKNOWN' : 'OFFLINE'

  return <><PageFrame profile={profile} connected={connected} activePage={activePage} onNavigate={setActivePage} onLogout={handleLogout}>
    <main className="dashboard">
      {dashboardError && <div className="panel page-panel">Backend dashboard data unavailable: {dashboardError}</div>}
      <div className="page-heading"><div><p className="eyebrow">COMMAND CENTER / OVERVIEW</p><h1>Network pulse</h1><p className="subhead">Self-healing control plane monitoring</p></div><div className="health-readout"><div className="health-ring" style={{ '--health': health === 'healthy' ? '360deg' : health === 'degraded' ? '180deg' : '0deg' }}><b>{health === 'unknown' ? unavailable : health.toUpperCase()}</b></div><div><span>NETWORK STATUS</span><strong>{health === 'unknown' ? unavailable : health.toUpperCase()}</strong><em>{data.status?.last_metric_at ? `Last sync ${new Date(data.status.last_metric_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Waiting for telemetry'}</em></div></div></div>
      <section className="panel network-identity-panel"><div className="panel-heading"><div><p className="eyebrow">MONITORING / NETWORK IDENTITY</p><h2>{networkInfo.connected_network_name || 'SSID Unavailable'}</h2></div><StatusBadge>{monitoringStatus}</StatusBadge></div><div className="identity-grid"><div><span>CONNECTED NETWORK / SSID</span><b>{connection.name || 'SSID Unavailable'}</b><small>{connection.status || 'NOT AVAILABLE'}</small></div><div><span>NETWORK TYPE</span><b>{networkInfo.network_type || unavailable}</b><small>{connection.status || 'NOT AVAILABLE'}</small></div><div><span>INTERFACE / IP ADDRESS</span><b>{connectionDetails.interface_id || unavailable}</b><small>{connectionDetails.ip_address || unavailable}</small></div><div><span>MONITORING TARGET</span><b>{networkInfo.monitoring_target || 'Target Unavailable'}</b><small>{latencyIsFresh ? 'Real measured latency' : 'Latency Data Unavailable'}</small></div><div><span>LATENCY</span><b>{!latencyIsFresh || networkInfo.latency_ms === null || networkInfo.latency_ms === undefined ? unavailable : `${Number(networkInfo.latency_ms).toFixed(2)} ms`}</b><small>{networkInfo.monitoring_target || 'Target Unavailable'}</small></div><div><span>UPLOAD / DOWNLOAD</span><b>{!uploadIsFresh || !downloadIsFresh || networkInfo.upload_throughput_bps === null || networkInfo.upload_throughput_bps === undefined || networkInfo.download_throughput_bps === null || networkInfo.download_throughput_bps === undefined ? unavailable : `${Number(networkInfo.upload_throughput_bps).toFixed(2)} B/s / ${Number(networkInfo.download_throughput_bps).toFixed(2)} B/s`}</b><small>Measured interface traffic</small></div><div><span>LINK CAPACITY</span><b>{networkInfo.link_capacity_mbps === null || networkInfo.link_capacity_mbps === undefined ? 'Capacity Unavailable' : `${networkInfo.link_capacity_mbps} Mbps`}</b><small>{networkInfo.capacity_status || 'Capacity Unavailable'}</small></div><div><span>LAST UPDATED</span><b>{networkInfo.last_detected_at ? new Date(networkInfo.last_detected_at).toLocaleString() : unavailable}</b><small>{monitoringIsFresh ? `Data ${new Date(connectionDetails.last_data_received).toLocaleString()}` : 'No recent metric data'}</small></div></div></section>
      <div className="panel service-status-panel">
        <div className="service-status-item"><strong>Frontend</strong><StatusBadge>ACTIVE</StatusBadge></div>
        <div className="service-status-item"><strong>Backend</strong><StatusBadge inProgress={backendHealth === 'CHECKING'}>{backendHealth}</StatusBadge></div>
        <div className="service-status-item"><strong>Database</strong><StatusBadge>{dashboardLoaded ? 'CONNECTED' : dashboardError ? 'UNVERIFIED' : 'CHECKING'}</StatusBadge></div>
        <div className="service-status-item"><strong>Monitoring</strong><StatusBadge>{monitoringStatus}</StatusBadge></div>
        <div className="service-status-item"><strong>ML model</strong><StatusBadge>{data.model?.status === 'loaded' ? 'LOADED' : 'UNAVAILABLE'}</StatusBadge></div>
        <div className="service-status-item"><strong>Inference</strong><StatusBadge>{inferenceStatus}</StatusBadge></div>
        <div className="service-status-item"><strong>SDN</strong><StatusBadge>{sdnControllerStatus}</StatusBadge></div>
        <div className="service-status-item"><strong>Recovery</strong><StatusBadge>{recoveryServiceStatus}</StatusBadge></div>
        <small>{modelStatus}; database connectivity is based on successful dashboard API queries.</small>
      </div>

      <section className="metrics-grid">
        <MetricCard label="NETWORK STATUS" value={networkStatus === 'unknown' ? unavailable : networkStatus.toUpperCase()} unit="" trend={data.status ? 'live' : ''} />
        <MetricCard label="LATENCY" value={latency} unit="ms" trend={latency !== null ? 'live' : ''} bars={getMetricSeries(['latency_ms', 'latency'])} />
        <MetricCard label="PACKET LOSS" value={packetLoss} unit="%" detail={`ICMP probe to ${networkInfo.monitoring_target || 'configured target'}`} trend={packetLoss !== null ? 'live' : ''} tone="green" bars={getMetricSeries(['packet_loss_pct', 'packet_loss'])} />
        <MetricCard label="BANDWIDTH" value={bandwidth} unit="%" detail={networkInfo.link_capacity_mbps ? `Measured utilization of ${networkInfo.link_capacity_mbps} Mbps link` : 'Interface link capacity unavailable'} trend={bandwidth !== null ? 'live' : ''} tone="amber" bars={getMetricSeries(['bandwidth_utilization_pct', 'bandwidth_usage', 'bandwidth_usage_pct'])} />
        <MetricCard label="TRAFFIC" value={traffic} unit="Mbps" trend={traffic !== null ? 'live' : ''} tone="cyan" bars={getMetricSeries(['throughput_mbps', 'throughput'])} />
        <MetricCard label="CPU" value={cpu} unit="%" trend={cpu !== null ? 'live' : ''} tone="coral" bars={getMetricSeries(['cpu_utilization_pct', 'cpu_usage_pct', 'cpu_usage'])} />
        <MetricCard label="MEMORY" value={memory} unit="%" detail={memoryDetail} trend={memory !== null ? 'live' : ''} tone="green" bars={getMetricSeries(['memory_utilization_pct', 'memory_usage_pct', 'memory_usage'])} />
        <MetricCard
          label="AVAILABILITY"
          value={availability}
          detail={monitoringIsFresh
            ? `Recent telemetry received from ${connectionDetails.interface_id || 'the connected interface'}`
            : connection.status === 'CONNECTED'
              ? 'Interface detected, but recent telemetry is unavailable'
              : 'No monitored network interface is connected'}
          tone="cyan"
          trend={monitoringIsFresh ? 'LIVE' : ''}
        />
        <article className="fault-card">
          <div className="metric-top"><span>ACTIVE FAULTS</span><span className="alert-count">{(data.faults?.length || 0).toString().padStart(2, '0')}</span></div>
          <strong>{fault ? fault.fault_type : 'NO ACTIVE FAULTS'}</strong>
          <p>{fault ? fault.affected_component : 'No active faults reported by backend'}</p>
          <StatusBadge>{fault ? fault.severity : 'CLEAR'}</StatusBadge>
        </article>
      </section>

      <div className="main-grid">
        <section className="panel topology-panel">
          <div className="panel-heading"><div><p className="eyebrow">READ-ONLY CONTROLLER MONITORING</p><h2>SDN controller &amp; topology</h2></div></div>
          <SdnControllerPanel snapshot={data.sdn} fault={fault} />
          <div className="interface-traffic">
            <div className="panel-heading"><div><p className="eyebrow">HOST INTERFACE TELEMETRY</p><h2>Interface traffic</h2></div></div>
            <TrafficFabric metrics={freshMetrics} interfaceId={connectionDetails.interface_id} controllerStatus={sdnControllerStatus} />
          </div>
        </section>
        <section className="panel prediction-panel"><div className="panel-heading"><div><p className="eyebrow">AI PREDICTION / MODEL {data.model?.version || unavailable}</p><h2>Signal interpretation</h2></div><span className="model-status">● {data.model?.status === 'loaded' ? 'ONLINE' : 'OFFLINE'}</span></div>
          {data.model?.status === 'loaded' ? <>
            <div className="prediction-main"><div className="prediction-orb" style={{ '--prediction-confidence': `${predictionConfidence}deg` }}><div><span>MODEL PROBABILITY</span><b>{Number.isFinite(numericPredictionProbability) ? `${Math.round(numericPredictionProbability * 100)}` : unavailable}{Number.isFinite(numericPredictionProbability) && <small>%</small>}</b></div></div><div className="prediction-label"><span>TOP MODEL CLASS · NOT A CONFIRMED INCIDENT</span><strong>{latestPrediction?.label || 'No prediction recorded'}</strong>{latestPrediction && <><small>{latestPrediction.timestamp ? new Date(latestPrediction.timestamp).toLocaleString() : unavailable}</small><small>{predictionBelowThreshold ? `Below ${(numericPredictionThreshold * 100).toFixed(0)}% threshold · inconclusive` : 'Model class only · no incident confirmed'}</small></>}</div></div>
            <div className="evidence-list"><p className="eyebrow">LATEST BACKEND PREDICTION</p>{latestPrediction ? <div className="evidence-row"><span>{predictionBelowThreshold ? 'Inconclusive model output' : 'Model output · not a confirmed incident'}</span><b>{Number.isFinite(Number(latestPrediction.probability)) ? `${Math.round(latestPrediction.probability * 100)}%` : unavailable}</b><small>{latestPrediction.prediction_id || unavailable}</small></div> : <div className="evidence-row"><span>Prediction</span><b>{unavailable}</b><small>No prediction record was returned by the backend.</small></div>}</div>
          </> : <div style={{ padding: 16, color: '#fbbf24' }}>ML model unavailable</div> }
        </section>
      </div>

      <div className="lower-grid"><section className="panel timeline-panel"><div className="panel-heading"><div><p className="eyebrow">RECOVERY STATUS</p><h2>{recoveryStatus.status || 'No recovery record'}</h2></div><span className="time-tag">{latestIncident?.timestamp ? new Date(latestIncident.timestamp).toLocaleString() : unavailable}</span></div>{recoveryStatus.active_recovery ? <pre className="json-view">{JSON.stringify(recoveryStatus.active_recovery, null, 2)}</pre> : <div className="empty-state">No recovery execution recorded by the backend.</div>}</section>
        <section className="panel explain-panel"><div className="panel-heading"><div><p className="eyebrow">EXPLAINABILITY</p><h2>Decision trace</h2></div><span className="trace-id">{latestIncident?.incident_id || 'No incident recorded'}</span></div><div className="trace-block"><div className="trace-icon">01</div><div><b>Recorded fault</b><p>{latestIncident?.detected_fault || fault?.fault_type || 'No incident recorded'}</p></div></div><div className="trace-block"><div className="trace-icon">02</div><div><b>Selected action</b><p>{latestIncident?.selected_action || recoveryStatus.active_recovery?.recommended_action || 'No decision recorded'}</p></div></div><div className="trace-block"><div className="trace-icon">03</div><div><b>Safety gate</b><p>{latestIncident?.safety_result ? (latestIncident.safety_result.safe ? 'Passed for this recorded action' : 'Blocked for this recorded action') : recoveryStatus.active_recovery?.safety_check || 'No safety check recorded'}</p></div></div></section></div>

      <section className="panel incidents-panel"><div className="panel-heading"><div><p className="eyebrow">INCIDENT HISTORY</p><h2>Recent events</h2></div><div className="filter-tabs">{['ALL', 'RESOLVED', 'FAILED', 'ESCALATED'].map(item => <button className={filter === item ? 'active' : ''} key={item} onClick={() => setFilter(item)}>{item}</button>)}</div></div><div className="incident-table"><div className="table-row table-header"><span>INCIDENT</span><span>TIME</span><span>FAULT TYPE</span><span>COMPONENT</span><span>ACTION</span><span>RESULT</span></div>{filteredIncidents.length ? filteredIncidents.map(item => <div className="table-row" key={item.incident_id}><span className="incident-id">{item.incident_id}</span><span>{item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : unavailable}</span><span>{item.detected_fault || unavailable}</span><span>{item.affected_component || unavailable}</span><span className="action-text">{item.selected_action || '—'}</span><span><StatusBadge>{item.final_status || 'OPEN'}</StatusBadge></span></div>) : <div className="table-row"><span>No incidents recorded</span><span>—</span><span>—</span><span>—</span><span>—</span><span>—</span></div>}</div></section>

      <section className="panel comparison-panel"><div className="panel-heading"><div><p className="eyebrow">RECOVERY VERIFICATION</p><h2>Recorded evidence</h2></div><span className="verified-tag">{latestIncident?.final_status || 'No incident result'}</span></div>{latestIncident?.verification_metrics ? <pre className="json-view">{JSON.stringify(latestIncident.verification_metrics, null, 2)}</pre> : <div className="empty-state">{latestIncident ? 'No verification metrics recorded by the backend.' : 'No incident recorded; recovery verification evidence does not exist.'}</div>}<small>Backend verification evidence does not independently prove that an OpenFlow switch changed state.</small></section>
    </main>
    <footer><span>SELFHEALNET CONTROL PLANE</span><span>MODEL LATENCY <b>{latency ?? unavailable}</b></span><span>LAST SYNC <b>{data.status?.last_metric_at ? new Date(data.status.last_metric_at).toISOString().slice(11, 19) + ' UTC' : 'N/A'}</b></span><span className="footer-safe">● {networkStatus === 'unknown' ? 'WAITING FOR TELEMETRY' : 'ALL SYSTEMS MONITORED'}</span></footer>
  </PageFrame><ToastViewport toasts={toasts} onDismiss={dismissToast} /></>
}

export default App
