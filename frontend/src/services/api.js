const API_BASE = import.meta.env.VITE_API_BASE || `${window.location.protocol}//${window.location.hostname}:8000/api/v1`
const TOKEN_KEY = 'selfhealnet_token'

function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function saveToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request(path, options = {}, fallback = null) {
  const token = getToken()
  const init = {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
    ...options,
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, init)
    const payload = await response.json().catch(() => null)
    if (!response.ok) {
      const detail = payload?.detail || payload?.message || 'Request failed'
      throw new Error(detail)
    }
    return payload
  } catch (error) {
    if (fallback !== null) return fallback
    throw error
  }
}

export async function loginUser(payload) {
  const result = await request('/auth/login', { method: 'POST', body: JSON.stringify(payload) })
  saveToken(result.token)
  return result
}

export async function registerUser(payload) {
  const result = await request('/auth/register', { method: 'POST', body: JSON.stringify(payload) })
  saveToken(result.token)
  return result
}

export async function logoutUser() {
  try {
    await request('/auth/logout', { method: 'POST' })
  } finally {
    saveToken(null)
  }
}

export async function forgotPassword(email) {
  return request('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) })
}

export async function verifyResetOtp(payload) {
  return request('/auth/verify-reset-otp', { method: 'POST', body: JSON.stringify(payload) })
}

export async function resetPassword(payload) {
  return request('/auth/reset-password', { method: 'POST', body: JSON.stringify(payload) })
}

export async function getProfile() {
  return request('/users/me')
}

export async function updateProfile(payload) {
  return request('/users/me', { method: 'PUT', body: JSON.stringify(payload) })
}

export async function getLoginHistory() {
  return request('/users/login-history')
}

export async function changePassword(payload) {
  return request('/users/change-password', { method: 'POST', body: JSON.stringify(payload) })
}

export async function getSettings() {
  return request('/users/settings')
}

export async function updateSettings(payload) {
  return request('/users/settings', { method: 'PUT', body: JSON.stringify(payload) })
}

export async function getAlerts() {
  return request('/alerts')
}

export async function getNotifications() {
  return request('/notifications')
}

async function get(path) {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: {
        ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
      },
    })
    if (!response.ok) throw new Error(`${response.status}`)
    return await response.json()
  } catch (error) {
    throw error
  }
}

function requireArray(payload, key, path) {
  if (!Array.isArray(payload?.[key])) {
    throw new Error(`Unexpected response from ${path}`)
  }
  return payload[key]
}

export async function getSdnStatus() {
  return get('/sdn/status')
}

export async function loadDashboard() {
  const [status, metrics, sdn, faults, incidents, predictions, model, networkInfo, recoveryStatus, memory] = await Promise.all([
    get('/network/status'),
    get('/metrics/live'),
    get('/sdn/status'),
    get('/faults/active'),
    get('/incidents'),
    get('/predictions'),
    get('/ml/model'),
    get('/network/info'),
    get('/recovery/status'),
    get('/system/memory'),
  ])

  return {
    status,
    metrics: requireArray(metrics, 'metrics', '/metrics/live'),
    topology: {
      nodes: requireArray(sdn?.topology, 'nodes', '/sdn/status'),
      links: requireArray(sdn?.topology, 'links', '/sdn/status'),
    },
    sdn,
    faults: requireArray(faults, 'faults', '/faults/active'),
    incidents: requireArray(incidents, 'incidents', '/incidents'),
    predictions: requireArray(predictions, 'predictions', '/predictions'),
    model,
    networkInfo,
    recoveryStatus,
    memory,
  }
}

export async function getPredictions() {
  return get('/predictions')
}

export async function checkBackendHealth() {
  const apiRoot = API_BASE.replace(/\/api\/v1\/?$/, '')
  const response = await fetch(`${apiRoot}/health`)
  if (!response.ok) throw new Error(`Backend health check failed (${response.status})`)
  const payload = await response.json()
  return payload?.status === 'healthy'
}

export async function getHistoricalMetrics(limit = 100) {
  return get(`/metrics/history?limit=${limit}`)
}

export async function getTopology() {
  return get('/topology')
}

export async function getRecoveryStatus() {
  return get('/recovery/status')
}

export async function getNetworkInfo() {
  return get('/network/info')
}
