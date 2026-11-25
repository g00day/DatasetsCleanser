import { baseUrl, endpoints } from './endpoints'

export async function request(key, options = {}) {
  const { id, params = {}, query = {}, method = 'GET', body, signal } = options
  const variables = { id, ...params }
  const path = endpoints[key].replace(/:(\w+)/g, (_, name) => encodeURIComponent(variables[name]))
  const url = new URL(baseUrl + path, location.origin)
  for (const [name, value] of Object.entries(query)) {
    if (value != null) url.searchParams.set(name, value)
  }

  const headers = { Accept: key === 'download' ? 'text/csv, application/json' : 'application/json' }
  const multipart = body instanceof FormData
  if (body && !multipart) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') {
    const { csrfToken } = await request('csrf', { signal })
    headers['X-CSRFToken'] = csrfToken
    if (['datasets', 'checks', 'cleaning', 'retryJob'].includes(key)) {
      headers['Idempotency-Key'] = crypto.randomUUID()
    }
  }

  const response = await fetch(url, {
    method, headers, signal,
    credentials: 'include',
    body: multipart ? body : JSON.stringify(body),
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}))
    const details = payload.error || {}
    const messages = Object.values(details.fields || {}).flat()
    const error = new Error(messages.join(' ') || details.message || 'Ошибка запроса (' + response.status + ')')
    error.status = response.status
    error.code = details.code
    error.fields = details.fields
    throw error
  }
  if (response.status === 204) return
  if (key === 'download') return response.blob()
  if (!response.headers.get('content-type')?.includes('json')) {
    throw new Error('Сервер API недоступен. Проверьте адрес подключения.')
  }
  return response.json()
}

export async function list(key, options = {}) {
  const items = []
  let page = 1
  while (true) {
    const result = await request(key, { ...options, query: { ...options.query, page } })
    items.push(...result.items)
    if (page >= result.pagination.totalPages) return items
    page++
  }
}

export async function waitForJob(id) {
  while (true) {
    const job = await request('job', { id })
    if (job.status === 'succeeded') return job
    if (!['queued', 'running'].includes(job.status)) {
      throw new Error(job.error?.message || 'Обработка завершилась ошибкой.')
    }
    await new Promise(resolve => setTimeout(resolve, 1200))
  }
}
