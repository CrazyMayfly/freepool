async function get(url) {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`)
  return resp.json()
}

async function post(url) {
  const resp = await fetch(url, { method: 'POST' })
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`)
  return resp.json()
}

async function put(url, body) {
  const resp = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`)
  return resp.json()
}

export const api = {
  overview: () => get('/api/overview'),
  tiers: () => get('/api/tiers'),
  series: (days = 30) => get(`/api/usage/series?days=${days}`),
  requests: (limit = 50) => get(`/api/requests?limit=${limit}`),
  catalog: () => get('/api/catalog'),
  syncCatalog: () => post('/api/catalog/sync'),
  updateQuota: (model, body) => put(`/api/quota/${encodeURIComponent(model)}`, body),
  settings: () => get('/api/settings'),
  updateService: (body) => put('/api/settings/service', body),
  updateTiers: (tiers) => put('/api/settings/tiers', { tiers }),
  updateDefaults: (body) => put('/api/settings/defaults', body),
  upstreamCheck: () => get('/api/settings/upstream-check'),
}

export function fmtTokens(v) {
  if (v == null) return '-'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + ' 亿'
  if (v >= 1e4) return (v / 1e4).toFixed(2) + ' 万'
  return String(v)
}

export const STATUS_META = {
  normal: { label: '正常', badge: 'badge-success' },
  low: { label: '偏低', badge: 'badge-warning' },
  exhausted: { label: '已耗尽', badge: 'badge-error' },
  expired: { label: '已过期', badge: 'badge-neutral' },
  offline: { label: '已下线', badge: 'badge-error' },
  unknown: { label: '未配置', badge: 'badge-ghost' },
}
